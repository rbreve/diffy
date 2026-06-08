"""Pydantic request/response models shared across the API."""

from pydantic import BaseModel


class FileEntry(BaseModel):
    """One changed file in a diff.

    :ivar path: Current path of the file (the "new" side).
    :ivar old_path: Previous path, set only for renames.
    :ivar status: One of ``added``, ``modified``, ``removed``, ``renamed``.
    :ivar additions: Number of added lines.
    :ivar deletions: Number of deleted lines.
    """

    path: str
    old_path: str | None = None
    status: str
    additions: int = 0
    deletions: int = 0


class DiffResponse(BaseModel):
    """Metadata for a loaded diff. File contents are fetched lazily."""

    diff_id: str
    title: str
    source: str  # "github" | "local"
    files: list[FileEntry]


class FileContent(BaseModel):
    """Full old/new text for a single file, used to render the Monaco diff."""

    path: str
    old_content: str = ""
    new_content: str = ""
    truncated: bool = False


class GitHubLoadRequest(BaseModel):
    """Request body for loading a GitHub pull request or commit."""

    url: str


class LocalLoadRequest(BaseModel):
    """Request body for diffing a local git repository."""

    repo_path: str
    base: str = ""  # blank -> auto-detect the default branch
    head: str = ""  # blank -> the working tree (uncommitted changes)


class RefsResponse(BaseModel):
    """Branches available in a local repository, for ref pickers."""

    current: str
    default_base: str
    branches: list[str]
    remotes: list[str]


class ChatMessage(BaseModel):
    """A single chat turn."""

    role: str  # "user" | "assistant"
    content: str


class ChatRequest(BaseModel):
    """Request body for the streaming chat endpoint."""

    diff_id: str
    messages: list[ChatMessage]
    focus_path: str | None = None


class DiffIdRequest(BaseModel):
    """Request body for AI endpoints that act on a whole diff."""

    diff_id: str


class SummaryResponse(BaseModel):
    """Plain-language summary of a change."""

    summary: str


class ExplainRequest(BaseModel):
    """Request body for explaining the changes in a single file."""

    diff_id: str
    path: str


class ExplainResponse(BaseModel):
    """Plain-language explanation of one file's changes."""

    explanation: str


class ConfigResponse(BaseModel):
    """Feature flags the frontend reads on boot.

    :ivar ai_enabled: Whether an Anthropic API key is configured. When false the
        frontend hides the AI pane entirely.
    """

    ai_enabled: bool
