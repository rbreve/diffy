"""Fetch diffs and file contents from the GitHub REST API."""

import base64
import re

import httpx

from .config import Settings
from .models import FileEntry
from .store import LoadedDiff, save

_API = "https://api.github.com"

_PR_RE = re.compile(r"github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+)/pull/(?P<number>\d+)")
_COMMIT_RE = re.compile(
    r"github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+)/commit/(?P<sha>[0-9a-fA-F]+)"
)


def _headers(settings: Settings) -> dict[str, str]:
    """Build request headers, including auth when a token is configured."""
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if settings.github_token:
        headers["Authorization"] = f"Bearer {settings.github_token}"
    return headers


def _normalize_status(status: str) -> str:
    """Map a GitHub file status onto the viewer's status vocabulary."""
    return {
        "added": "added",
        "removed": "removed",
        "modified": "modified",
        "renamed": "renamed",
        "changed": "modified",
        "copied": "added",
    }.get(status, "modified")


async def load_github(url: str, settings: Settings) -> LoadedDiff:
    """Load a GitHub pull request or commit into the diff store.

    :param url: A ``.../pull/<n>`` or ``.../commit/<sha>`` URL.
    :param settings: Active settings (provides the optional token).
    :returns: The stored :class:`LoadedDiff`.
    :raises ValueError: If the URL is not a recognised PR or commit link.
    :raises httpx.HTTPStatusError: If GitHub returns an error status.
    """
    async with httpx.AsyncClient(timeout=30, headers=_headers(settings)) as client:
        if match := _PR_RE.search(url):
            return await _load_pr(client, match, settings)
        if match := _COMMIT_RE.search(url):
            return await _load_commit(client, match, settings)
    raise ValueError("URL must be a GitHub pull request or commit link.")


async def _paged_files(client: httpx.AsyncClient, files_url: str) -> list[dict]:
    """Fetch all pages of a file-listing endpoint."""
    files: list[dict] = []
    page = 1
    while True:
        resp = await client.get(files_url, params={"per_page": 100, "page": page})
        resp.raise_for_status()
        batch = resp.json()
        files.extend(batch)
        if len(batch) < 100:
            return files
        page += 1


def _build_entries(raw_files: list[dict]) -> tuple[list[FileEntry], dict[str, str]]:
    """Convert raw GitHub file objects into entries and a patch map."""
    entries: list[FileEntry] = []
    patches: dict[str, str] = {}
    for item in raw_files:
        path = item["filename"]
        entries.append(
            FileEntry(
                path=path,
                old_path=item.get("previous_filename"),
                status=_normalize_status(item.get("status", "modified")),
                additions=item.get("additions", 0),
                deletions=item.get("deletions", 0),
            )
        )
        if patch := item.get("patch"):
            patches[path] = patch
    return entries, patches


async def _load_pr(client: httpx.AsyncClient, match: re.Match, settings: Settings) -> LoadedDiff:
    """Load a pull request given its URL match groups."""
    owner, repo, number = match["owner"], match["repo"], match["number"]
    meta_resp = await client.get(f"{_API}/repos/{owner}/{repo}/pulls/{number}")
    meta_resp.raise_for_status()
    pr = meta_resp.json()

    raw_files = await _paged_files(client, f"{_API}/repos/{owner}/{repo}/pulls/{number}/files")
    entries, patches = _build_entries(raw_files)

    return save(
        title=f"#{number} {pr.get('title', '')}".strip(),
        source="github",
        files=entries,
        patches=patches,
        meta={
            "owner": owner,
            "repo": repo,
            "base_sha": pr["base"]["sha"],
            "head_sha": pr["head"]["sha"],
        },
    )


async def _load_commit(client: httpx.AsyncClient, match: re.Match, settings: Settings) -> LoadedDiff:
    """Load a single commit given its URL match groups."""
    owner, repo, sha = match["owner"], match["repo"], match["sha"]
    resp = await client.get(f"{_API}/repos/{owner}/{repo}/commits/{sha}")
    resp.raise_for_status()
    commit = resp.json()

    entries, patches = _build_entries(commit.get("files", []))
    parents = commit.get("parents", [])
    base_sha = parents[0]["sha"] if parents else sha
    subject = commit.get("commit", {}).get("message", "").splitlines()[0] if commit.get("commit") else sha[:7]

    return save(
        title=f"{sha[:7]} {subject}".strip(),
        source="github",
        files=entries,
        patches=patches,
        meta={"owner": owner, "repo": repo, "base_sha": base_sha, "head_sha": commit["sha"]},
    )


async def _content_at(
    client: httpx.AsyncClient, owner: str, repo: str, path: str, ref: str, max_bytes: int
) -> tuple[str, bool]:
    """Return the UTF-8 text of ``path`` at ``ref``.

    :returns: A ``(text, truncated)`` pair. ``text`` is empty when the file
        does not exist at that ref (e.g. an added or removed file).
    """
    resp = await client.get(
        f"{_API}/repos/{owner}/{repo}/contents/{path}", params={"ref": ref}
    )
    if resp.status_code == 404:
        return "", False
    resp.raise_for_status()
    payload = resp.json()
    if payload.get("size", 0) > max_bytes or payload.get("encoding") != "base64":
        return "", True
    try:
        raw = base64.b64decode(payload["content"])
        return raw.decode("utf-8"), False
    except (UnicodeDecodeError, ValueError):
        return "", True


async def file_contents(diff: LoadedDiff, path: str, settings: Settings) -> tuple[str, str, bool]:
    """Fetch old and new contents of ``path`` for a stored GitHub diff.

    :returns: ``(old_text, new_text, truncated)``.
    """
    meta = diff.meta
    entry = next((f for f in diff.files if f.path == path), None)
    old_path = entry.old_path if entry and entry.old_path else path
    async with httpx.AsyncClient(timeout=30, headers=_headers(settings)) as client:
        old, t_old = await _content_at(
            client, meta["owner"], meta["repo"], old_path, meta["base_sha"], settings.max_file_bytes
        )
        new, t_new = await _content_at(
            client, meta["owner"], meta["repo"], path, meta["head_sha"], settings.max_file_bytes
        )
    return old, new, t_old or t_new
