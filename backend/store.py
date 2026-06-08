"""In-memory store of loaded diffs, keyed by a generated id.

A loaded diff holds the cheap-to-fetch metadata (file list and per-file
patches) plus the information needed to lazily fetch full file contents and
build AI context. State lives only for the lifetime of the process, which is
fine for a single-user local tool.
"""

import uuid
from dataclasses import dataclass, field

from .models import FileEntry


@dataclass
class LoadedDiff:
    """A diff that has been fetched and is available for viewing/AI.

    :ivar diff_id: Opaque handle returned to the frontend.
    :ivar title: Human-readable title (PR title, commit subject, ref range).
    :ivar source: ``"github"`` or ``"local"``.
    :ivar files: Changed-file metadata.
    :ivar patches: Map of file path to its unified-diff hunk text.
    :ivar meta: Source-specific data needed for lazy content fetches
        (GitHub: owner/repo/base_sha/head_sha; local: repo_path/base/head).
    """

    diff_id: str
    title: str
    source: str
    files: list[FileEntry]
    patches: dict[str, str] = field(default_factory=dict)
    meta: dict = field(default_factory=dict)


_STORE: dict[str, LoadedDiff] = {}


def save(title: str, source: str, files: list[FileEntry], patches: dict[str, str], meta: dict) -> LoadedDiff:
    """Create and store a :class:`LoadedDiff`, returning it.

    :param title: Human-readable title.
    :param source: ``"github"`` or ``"local"``.
    :param files: Changed-file metadata.
    :param patches: Map of path to unified-diff text.
    :param meta: Source-specific fetch metadata.
    :returns: The stored diff, with a freshly generated ``diff_id``.
    """
    diff_id = uuid.uuid4().hex[:12]
    diff = LoadedDiff(
        diff_id=diff_id, title=title, source=source, files=files, patches=patches, meta=meta
    )
    _STORE[diff_id] = diff
    return diff


def get(diff_id: str) -> LoadedDiff | None:
    """Return the stored diff for ``diff_id`` or ``None`` if unknown."""
    return _STORE.get(diff_id)
