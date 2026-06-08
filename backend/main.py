"""FastAPI application: serves the static frontend and the diff/AI API."""

from pathlib import Path

import httpx
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import ai, github, gitlocal, store
from .config import Settings, get_settings
from .models import (
    ChatRequest,
    ConfigResponse,
    DiffIdRequest,
    DiffResponse,
    ExplainRequest,
    ExplainResponse,
    FileContent,
    GitHubLoadRequest,
    LocalLoadRequest,
    RefsResponse,
    SummaryResponse,
)

app = FastAPI(title="Diffy", description="A nicer GitHub diff viewer with AI.")

_FRONTEND = Path(__file__).resolve().parent.parent / "frontend"


@app.get("/api/config", response_model=ConfigResponse)
async def get_config(settings: Settings = Depends(get_settings)) -> ConfigResponse:
    """Report which optional features are enabled by the environment."""
    ai_enabled = bool(settings.anthropic_api_key or settings.openrouter_api_key)
    return ConfigResponse(ai_enabled=ai_enabled)


def _diff_or_404(diff_id: str) -> store.LoadedDiff:
    """Return the stored diff or raise a 404."""
    diff = store.get(diff_id)
    if diff is None:
        raise HTTPException(status_code=404, detail="Unknown diff_id; load a diff first.")
    return diff


@app.post("/api/diff/github", response_model=DiffResponse)
async def load_github_diff(
    req: GitHubLoadRequest, settings: Settings = Depends(get_settings)
) -> DiffResponse:
    """Load a GitHub pull request or commit by URL."""
    try:
        diff = await github.load_github(req.url, settings)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code, detail=exc.response.text) from exc
    return DiffResponse(diff_id=diff.diff_id, title=diff.title, source=diff.source, files=diff.files)


@app.post("/api/diff/local", response_model=DiffResponse)
async def load_local_diff(
    req: LocalLoadRequest, settings: Settings = Depends(get_settings)
) -> DiffResponse:
    """Diff two refs in a local git repository."""
    try:
        diff = await gitlocal.load_local(req.repo_path, req.base, req.head, settings)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return DiffResponse(diff_id=diff.diff_id, title=diff.title, source=diff.source, files=diff.files)


@app.get("/api/local/refs", response_model=RefsResponse)
async def local_refs(repo_path: str = Query(...)) -> RefsResponse:
    """List branches in a local repository to populate the ref pickers."""
    try:
        return RefsResponse(**await gitlocal.list_refs(repo_path))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/file", response_model=FileContent)
async def get_file(
    diff_id: str = Query(...),
    path: str = Query(...),
    settings: Settings = Depends(get_settings),
) -> FileContent:
    """Fetch the full old/new contents of one file in a loaded diff."""
    diff = _diff_or_404(diff_id)
    try:
        if diff.source == "github":
            old, new, truncated = await github.file_contents(diff, path, settings)
        else:
            old, new, truncated = await gitlocal.file_contents(diff, path, settings)
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code, detail=exc.response.text) from exc
    return FileContent(path=path, old_content=old, new_content=new, truncated=truncated)


@app.post("/api/ai/chat")
async def ai_chat(req: ChatRequest, settings: Settings = Depends(get_settings)) -> StreamingResponse:
    """Stream a chat reply about the loaded diff as plain text."""
    diff = _diff_or_404(req.diff_id)
    focus_content: str | None = None
    if req.focus_path:
        try:
            if diff.source == "github":
                _, focus_content, _ = await github.file_contents(diff, req.focus_path, settings)
            else:
                _, focus_content, _ = await gitlocal.file_contents(diff, req.focus_path, settings)
        except httpx.HTTPStatusError:
            focus_content = None

    async def generate():
        try:
            async for chunk in ai.stream_chat(diff, req.messages, focus_content, settings):
                yield chunk
        except ValueError as exc:
            yield f"\n\n[error: {exc}]"

    return StreamingResponse(generate(), media_type="text/plain; charset=utf-8")


@app.post("/api/ai/summary", response_model=SummaryResponse)
async def ai_summary(req: DiffIdRequest, settings: Settings = Depends(get_settings)) -> SummaryResponse:
    """Return a plain-language summary of the loaded diff."""
    diff = _diff_or_404(req.diff_id)
    try:
        return SummaryResponse(summary=await ai.summarize(diff, settings))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/ai/explain", response_model=ExplainResponse)
async def ai_explain(req: ExplainRequest, settings: Settings = Depends(get_settings)) -> ExplainResponse:
    """Explain the changes in a single file, given its full contents and diff."""
    diff = _diff_or_404(req.diff_id)
    try:
        if diff.source == "github":
            _, new_content, _ = await github.file_contents(diff, req.path, settings)
        else:
            _, new_content, _ = await gitlocal.file_contents(diff, req.path, settings)
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code, detail=exc.response.text) from exc

    patch = diff.patches.get(req.path)
    try:
        explanation = await ai.explain_file(req.path, patch, new_content, settings)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ExplainResponse(explanation=explanation)


# Static frontend is mounted last so the /api routes above take precedence.
app.mount("/", StaticFiles(directory=_FRONTEND, html=True), name="frontend")
