"""AI-powered features: chat, summary, and inline review comments.

Two providers are supported and selected from the environment:

* **Anthropic** (default) — calls the Claude API directly. The combined unified
  diff is sent as a cached context block so repeated calls about the same change
  reuse the prompt cache and stay cheap.
* **OpenRouter** — used when ``OPENROUTER_API_KEY`` is set. OpenRouter exposes an
  OpenAI-compatible API, so it is driven through the ``openai`` SDK pointed at
  OpenRouter's base URL, with the model taken from ``OPENROUTER_MODEL``.

If both keys are present, OpenRouter takes precedence.
"""

from collections.abc import AsyncIterator

from anthropic import AsyncAnthropic
from openai import AsyncOpenAI

from .config import Settings
from .models import ChatMessage
from .store import LoadedDiff

_MAX_CONTEXT_CHARS = 120_000

_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

_REVIEWER_PREAMBLE = (
    "You are an expert code reviewer helping a developer understand a change. "
    "You are given the unified diff (patches) of every changed file. Be precise, "
    "reference file paths and line numbers, and keep answers grounded in the diff."
)

_SUMMARY_PROMPT = (
    "Summarize this change for a reviewer. Cover: what it does, why "
    "(if inferable), notable files, and anything risky to watch for. "
    "Use short markdown sections and bullet points."
)

_EXPLAIN_PROMPT = (
    "Explain the changes made to this file. Walk through what changed and why it "
    "matters, referencing line numbers where helpful, and call out anything risky. "
    "Keep it concise and use short markdown sections or bullet points."
)


def _combined_patches(diff: LoadedDiff) -> str:
    """Concatenate per-file patches into a single budgeted text block."""
    chunks: list[str] = []
    total = 0
    for entry in diff.files:
        patch = diff.patches.get(entry.path)
        header = f"\n=== {entry.path} ({entry.status}, +{entry.additions} -{entry.deletions}) ===\n"
        body = header + (patch or "(no textual patch available)\n")
        if total + len(body) > _MAX_CONTEXT_CHARS:
            chunks.append(f"\n... ({len(diff.files) - len(chunks)} more files omitted for length)\n")
            break
        chunks.append(body)
        total += len(body)
    return "".join(chunks)


def _diff_context_text(diff: LoadedDiff) -> str:
    """Build the plain-text description of the change shared by both providers."""
    return (
        f"{_REVIEWER_PREAMBLE}\n\n"
        f"CHANGE TITLE: {diff.title}\n"
        f"SOURCE: {diff.source}\n"
        f"FILES CHANGED: {len(diff.files)}\n\n"
        f"UNIFIED DIFF:\n{_combined_patches(diff)}"
    )


def _focus_text(focus_content: str) -> str:
    """Render the open-file context block."""
    return f"FULL CONTENT OF THE FILE CURRENTLY OPEN:\n{focus_content[:_MAX_CONTEXT_CHARS]}"


def _file_context_text(path: str, patch: str | None, new_content: str | None) -> str:
    """Build the context for explaining a single file's changes."""
    return (
        f"{_REVIEWER_PREAMBLE}\n\n"
        f"FILE: {path}\n\n"
        f"DIFF FOR THIS FILE:\n{patch or '(no textual patch available)'}\n\n"
        f"FULL NEW CONTENT OF THIS FILE:\n{(new_content or '')[:_MAX_CONTEXT_CHARS]}"
    )


# ---------- Anthropic provider ----------


class AnthropicProvider:
    """AI features backed by the Anthropic Claude API (with prompt caching)."""

    def __init__(self, settings: Settings) -> None:
        self._client = AsyncAnthropic(api_key=settings.anthropic_api_key)
        self._model = settings.anthropic_model

    def _system(self, diff: LoadedDiff, focus_content: str | None = None) -> list[dict]:
        """Build the cached system blocks describing the change."""
        blocks: list[dict] = [
            {
                "type": "text",
                "text": _diff_context_text(diff),
                "cache_control": {"type": "ephemeral"},
            }
        ]
        if focus_content:
            blocks.append({"type": "text", "text": _focus_text(focus_content)})
        return blocks

    async def stream_chat(
        self, diff: LoadedDiff, messages: list[ChatMessage], focus_content: str | None
    ) -> AsyncIterator[str]:
        async with self._client.messages.stream(
            model=self._model,
            max_tokens=2048,
            system=self._system(diff, focus_content),
            messages=[{"role": m.role, "content": m.content} for m in messages],
        ) as stream:
            async for text in stream.text_stream:
                yield text

    async def summarize(self, diff: LoadedDiff) -> str:
        resp = await self._client.messages.create(
            model=self._model,
            max_tokens=1024,
            system=self._system(diff),
            messages=[{"role": "user", "content": _SUMMARY_PROMPT}],
        )
        return "".join(block.text for block in resp.content if block.type == "text")

    async def explain_file(
        self, path: str, patch: str | None, new_content: str | None
    ) -> str:
        resp = await self._client.messages.create(
            model=self._model,
            max_tokens=1500,
            system=[{"type": "text", "text": _file_context_text(path, patch, new_content)}],
            messages=[{"role": "user", "content": _EXPLAIN_PROMPT}],
        )
        return "".join(block.text for block in resp.content if block.type == "text")


# ---------- OpenRouter provider (OpenAI-compatible) ----------


class OpenRouterProvider:
    """AI features backed by OpenRouter via the OpenAI-compatible API."""

    def __init__(self, settings: Settings) -> None:
        self._client = AsyncOpenAI(
            api_key=settings.openrouter_api_key,
            base_url=_OPENROUTER_BASE_URL,
            default_headers={"X-Title": "Diffy"},
        )
        self._model = settings.openrouter_model

    def _system(self, diff: LoadedDiff, focus_content: str | None = None) -> str:
        """Build the system prompt; focus content is appended inline."""
        text = _diff_context_text(diff)
        if focus_content:
            text += f"\n\n{_focus_text(focus_content)}"
        return text

    async def stream_chat(
        self, diff: LoadedDiff, messages: list[ChatMessage], focus_content: str | None
    ) -> AsyncIterator[str]:
        convo = [{"role": "system", "content": self._system(diff, focus_content)}]
        convo += [{"role": m.role, "content": m.content} for m in messages]
        stream = await self._client.chat.completions.create(
            model=self._model,
            max_tokens=2048,
            messages=convo,
            stream=True,
        )
        async for chunk in stream:
            if chunk.choices and (delta := chunk.choices[0].delta.content):
                yield delta

    async def summarize(self, diff: LoadedDiff) -> str:
        resp = await self._client.chat.completions.create(
            model=self._model,
            max_tokens=1024,
            messages=[
                {"role": "system", "content": self._system(diff)},
                {"role": "user", "content": _SUMMARY_PROMPT},
            ],
        )
        return resp.choices[0].message.content or ""

    async def explain_file(
        self, path: str, patch: str | None, new_content: str | None
    ) -> str:
        resp = await self._client.chat.completions.create(
            model=self._model,
            max_tokens=1500,
            messages=[
                {"role": "system", "content": _file_context_text(path, patch, new_content)},
                {"role": "user", "content": _EXPLAIN_PROMPT},
            ],
        )
        return resp.choices[0].message.content or ""


# ---------- Provider selection + public API ----------

type Provider = AnthropicProvider | OpenRouterProvider


def _provider(settings: Settings) -> Provider:
    """Return the configured AI provider or raise if none is available.

    OpenRouter takes precedence when its key is set; otherwise Anthropic is used.
    """
    if settings.openrouter_api_key:
        return OpenRouterProvider(settings)
    if settings.anthropic_api_key:
        return AnthropicProvider(settings)
    raise ValueError(
        "No AI provider configured; set OPENROUTER_API_KEY or ANTHROPIC_API_KEY."
    )


async def stream_chat(
    diff: LoadedDiff,
    messages: list[ChatMessage],
    focus_content: str | None,
    settings: Settings,
) -> AsyncIterator[str]:
    """Stream a chat reply grounded in the diff.

    :yields: Text deltas as they arrive from the model.
    """
    async for chunk in _provider(settings).stream_chat(diff, messages, focus_content):
        yield chunk


async def summarize(diff: LoadedDiff, settings: Settings) -> str:
    """Return a plain-language summary of the change."""
    return await _provider(settings).summarize(diff)


async def explain_file(
    path: str,
    patch: str | None,
    new_content: str | None,
    settings: Settings,
) -> str:
    """Return a plain-language explanation of one file's changes."""
    return await _provider(settings).explain_file(path, patch, new_content)
