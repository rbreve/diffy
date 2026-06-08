"""Diff a local git repository by shelling out to ``git``."""

import asyncio
from pathlib import Path

from .config import Settings
from .models import FileEntry
from .store import LoadedDiff, save


async def _git(repo: Path, *args: str) -> tuple[int, str, str]:
    """Run ``git`` in ``repo`` and capture its output.

    :returns: ``(returncode, stdout, stderr)`` with text decoded as UTF-8.
    """
    proc = await asyncio.create_subprocess_exec(
        "git",
        "-C",
        str(repo),
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, err = await proc.communicate()
    return proc.returncode or 0, out.decode("utf-8", "replace"), err.decode("utf-8", "replace")


def _status_letter(letter: str) -> str:
    """Map a ``git`` status letter onto the viewer's status vocabulary."""
    return {"A": "added", "D": "removed", "M": "modified", "R": "renamed", "C": "added"}.get(
        letter[0], "modified"
    )


def _split_combined_patch(diff_text: str) -> dict[str, str]:
    """Split a combined ``git diff`` into a map of new-path to its hunk text."""
    patches: dict[str, str] = {}
    current_path: str | None = None
    lines: list[str] = []
    for line in diff_text.splitlines(keepends=True):
        if line.startswith("diff --git "):
            if current_path is not None:
                patches[current_path] = "".join(lines)
            lines = [line]
            # "diff --git a/<old> b/<new>" -> take the b/ side
            parts = line.split(" b/", 1)
            current_path = parts[1].strip() if len(parts) == 2 else None
        else:
            lines.append(line)
    if current_path is not None:
        patches[current_path] = "".join(lines)
    return patches


def _is_worktree(head: str) -> bool:
    """Return whether ``head`` means "the working tree" (uncommitted changes)."""
    return head.strip().lower() in ("", ".", "worktree", "working-tree")


async def _default_base(repo: Path) -> str:
    """Pick a sensible base when none was supplied.

    Prefers the remote's default branch (``origin/HEAD``), then common local
    branch names, falling back to ``HEAD``.
    """
    code, out, _ = await _git(repo, "symbolic-ref", "--short", "refs/remotes/origin/HEAD")
    if code == 0 and out.strip():
        return out.strip()
    for candidate in ("develop", "main", "master"):
        code, _, _ = await _git(repo, "rev-parse", "--verify", candidate)
        if code == 0:
            return candidate
    return "HEAD"


async def list_refs(repo_path: str) -> dict:
    """List the branches in a local repository for the ref pickers.

    :param repo_path: Path to a git working tree.
    :returns: ``{current, default_base, branches, remotes}``.
    :raises ValueError: If the path is not a git repository.
    """
    repo = Path(repo_path).expanduser()
    if not repo.is_dir():
        raise ValueError(f"Not a directory: {repo_path}")
    code, _, _ = await _git(repo, "rev-parse", "--is-inside-work-tree")
    if code != 0:
        raise ValueError(f"Not a git repository: {repo_path}")

    _, current, _ = await _git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    _, locals_out, _ = await _git(repo, "for-each-ref", "--format=%(refname:short)", "refs/heads")
    # Use the full refname for remotes so the symbolic "origin/HEAD" pointer
    # (which shortens to a bare "origin") can be filtered out reliably.
    _, remotes_out, _ = await _git(repo, "for-each-ref", "--format=%(refname)", "refs/remotes")

    branches = [b for b in locals_out.splitlines() if b.strip()]
    remotes = [
        ref.removeprefix("refs/remotes/")
        for ref in (line.strip() for line in remotes_out.splitlines())
        if ref and not ref.endswith("/HEAD")
    ]
    return {
        "current": current.strip(),
        "default_base": await _default_base(repo),
        "branches": branches,
        "remotes": remotes,
    }


async def load_local(repo_path: str, base: str, head: str, settings: Settings) -> LoadedDiff:
    """Load a diff for a local repository.

    Leave ``head`` blank to review the **working tree** (uncommitted changes —
    both staged and unstaged, plus untracked files). Otherwise ``head`` is a
    ref and the change is the commit range ``base..head``.

    :param repo_path: Path to a git working tree.
    :param base: Base ref (left side). Blank auto-detects the default branch.
    :param head: Head ref, or blank for the working tree.
    :param settings: Active settings (governs the max file size).
    :returns: The stored :class:`LoadedDiff`.
    :raises ValueError: If the path is not a git repository or refs are invalid.
    """
    repo = Path(repo_path).expanduser()
    if not repo.is_dir():
        raise ValueError(f"Not a directory: {repo_path}")
    code, _, _ = await _git(repo, "rev-parse", "--is-inside-work-tree")
    if code != 0:
        raise ValueError(f"Not a git repository: {repo_path}")

    if not base.strip():
        base = await _default_base(repo)
    worktree = _is_worktree(head)

    # Diff from the merge-base so the result matches GitHub's PR view: only the
    # changes introduced on this branch since it diverged from `base`, rather
    # than a raw two-dot diff that would surface base's own newer commits as
    # noise. For the working tree, that fork point is measured against HEAD.
    mb_code, mb_out, _ = await _git(repo, "merge-base", base, "HEAD" if worktree else head)
    effective_base = mb_out.strip() if mb_code == 0 and mb_out.strip() else base

    # When `head` is the working tree we omit it, so `git diff` compares the
    # base against the files on disk (staged + unstaged).
    tail = [effective_base] if worktree else [effective_base, head]
    code, numstat, err = await _git(repo, "diff", "--numstat", "-M", *tail)
    if code != 0:
        raise ValueError(err.strip() or "git diff failed")
    _, namestatus, _ = await _git(repo, "diff", "--name-status", "-M", *tail)
    _, combined, _ = await _git(repo, "diff", "-M", *tail)

    stats: dict[str, tuple[int, int]] = {}
    for line in numstat.splitlines():
        cols = line.split("\t")
        if len(cols) >= 3:
            add = int(cols[0]) if cols[0].isdigit() else 0
            dele = int(cols[1]) if cols[1].isdigit() else 0
            stats[cols[-1]] = (add, dele)

    entries: list[FileEntry] = []
    for line in namestatus.splitlines():
        cols = line.split("\t")
        if len(cols) < 2:
            continue
        status = _status_letter(cols[0])
        if status == "renamed" and len(cols) >= 3:
            old_path, path = cols[1], cols[2]
        else:
            old_path, path = (None, cols[1])
        add, dele = stats.get(path, (0, 0))
        entries.append(
            FileEntry(path=path, old_path=old_path, status=status, additions=add, deletions=dele)
        )

    # Untracked files never appear in `git diff`; surface them as additions.
    if worktree:
        known = {e.path for e in entries}
        _, untracked, _ = await _git(repo, "ls-files", "--others", "--exclude-standard")
        for path in (ln.strip() for ln in untracked.splitlines()):
            if path and path not in known:
                text, truncated = _read_worktree_file(repo / path, settings.max_file_bytes)
                added = 0 if truncated else text.count("\n") + (1 if text and not text.endswith("\n") else 0)
                entries.append(FileEntry(path=path, status="added", additions=added))

    head_label = "working tree" if worktree else head
    return save(
        title=f"{base} → {head_label}  ({repo.name})",
        source="local",
        files=entries,
        patches=_split_combined_patch(combined),
        meta={"repo_path": str(repo), "base": effective_base, "head": head, "worktree": worktree},
    )


async def _show(repo: Path, ref: str, path: str, max_bytes: int) -> tuple[str, bool]:
    """Return the text of ``path`` at ``ref`` via ``git show``."""
    code, out, _ = await _git(repo, "show", f"{ref}:{path}")
    if code != 0:
        return "", False  # file absent at this ref (added/removed)
    if len(out.encode("utf-8", "replace")) > max_bytes or "\x00" in out:
        return "", True
    return out, False


def _read_worktree_file(path: Path, max_bytes: int) -> tuple[str, bool]:
    """Read a file from disk as UTF-8 text, flagging oversized/binary files."""
    try:
        data = path.read_bytes()
    except OSError:
        return "", False  # missing on disk (e.g. deleted in the working tree)
    if len(data) > max_bytes:
        return "", True
    try:
        return data.decode("utf-8"), False
    except UnicodeDecodeError:
        return "", True


async def file_contents(diff: LoadedDiff, path: str, settings: Settings) -> tuple[str, str, bool]:
    """Fetch old and new contents of ``path`` for a stored local diff.

    The new side comes from disk when the diff targets the working tree, and
    from ``git show <head>`` otherwise.

    :returns: ``(old_text, new_text, truncated)``.
    """
    meta = diff.meta
    repo = Path(meta["repo_path"])
    entry = next((f for f in diff.files if f.path == path), None)
    old_path = entry.old_path if entry and entry.old_path else path
    old, t_old = await _show(repo, meta["base"], old_path, settings.max_file_bytes)
    if meta.get("worktree"):
        new, t_new = _read_worktree_file(repo / path, settings.max_file_bytes)
    else:
        new, t_new = await _show(repo, meta["head"], path, settings.max_file_bytes)
    return old, new, t_old or t_new
