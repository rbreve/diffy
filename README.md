# Diffy

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/)
[![PRs welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](#contributing)

A nicer way to read code diffs. GitHub's diff view is cramped — forced hunks, no full-file
context, a split screen that hides half the code. **Diffy** renders diffs with the VS Code
engine (Monaco): whole files with changes highlighted, resizable panes, full font/theme control,
a distraction-free full-screen mode, and an optional AI side-panel that can answer questions about
the change, summarize it, and explain the changes in the file you're viewing.

It reads diffs from **GitHub** (pull-request and commit URLs) *and* from **local git
repositories** — including your **uncommitted working-tree changes**, so you can review a branch
before you even commit.

<img width="1441" height="682" alt="Screenshot 2026-06-08 at 15 00 04" src="https://github.com/user-attachments/assets/ab0b74e8-866d-4e19-bac5-7f759824a2a4" />


> **Stack:** vanilla JS + [Monaco](https://microsoft.github.io/monaco-editor/) (loaded from CDN, no
> build step) on the front end, and a thin [FastAPI](https://fastapi.tiangolo.com/) backend that
> fetches diffs and proxies the AI provider — [Claude](https://www.anthropic.com/) directly or any
> model via [OpenRouter](https://openrouter.ai/).

---

## Features

- **Whole-file diffs** — see the entire file with changes highlighted, fold unchanged regions,
  and toggle inline ↔ side-by-side. No more squinting at isolated hunks.
- **Two diff sources:**
  - **GitHub** — paste a pull-request (`.../pull/123`) or commit (`.../commit/<sha>`) URL.
  - **Local git** — point at a repo, pick **base** and **head** from branch dropdowns, or leave
    head on **Working tree** to review *uncommitted* changes (staged, unstaged, and untracked).
    Uses merge-base semantics, so a local diff reads like the eventual PR.
- **Optional AI panel (Claude or OpenRouter):**
  - **Chat** — ask questions about the change; the open file's full contents are included as context.
  - **Summary** — a plain-language overview of what the change does.
  - **Explain** — a focused walkthrough of the changes in the file you're currently viewing
    (sends that file's full contents *and* its diff to the model).
  - Works with **Anthropic** directly or with **any model via [OpenRouter](https://openrouter.ai/)**
    (OpenAI, Gemini, Llama, …) — just set the matching key in `.env`.
  - The panel only appears when an AI key is configured — without one, Diffy is a pure diff viewer
    and the AI pane is hidden entirely.
- **Comfortable UI** — resizable panes (files · diff · AI), adjustable font size, light/dark/
  high-contrast themes, word wrap, and a **full-screen** mode that strips everything but the code
  and file navigation.
- **Bundled code fonts** — System mono, JetBrains Mono, Fira Code, and Fantasque Sans Mono, with
  ligatures.
- **Keyboard navigation** — `Alt + ←/→` to move between files, `Esc` to exit full screen.

---

## Prerequisites

- **Python 3.11+**
- **git** (only needed for the local-repository mode)
- An internet connection (Monaco and a couple of small libraries load from a CDN)
- Optional:
  - A **GitHub token** — raises API rate limits and unlocks private repositories.
  - An **AI key** for the AI features — either an **Anthropic API key** or an **OpenRouter API key**.
    Without one, diff viewing still works and the AI pane is simply hidden.

---

## Setup

```bash
git clone https://github.com/<owner>/diffy.git
cd diffy

python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env               # then edit .env (see below)
```

### Configure `.env`

Pick **one** AI provider (or none). If `OPENROUTER_API_KEY` is set it takes precedence over
`ANTHROPIC_API_KEY`.

| Variable             | Required for                | Notes                                                  |
|----------------------|-----------------------------|--------------------------------------------------------|
| `GITHUB_TOKEN`       | private repos / rate limits | Optional for public repos                              |
| `ANTHROPIC_API_KEY`  | AI features (Anthropic)     | Calls Claude directly                                  |
| `ANTHROPIC_MODEL`    | —                           | Defaults to `claude-sonnet-4-6`                        |
| `OPENROUTER_API_KEY` | AI features (OpenRouter)    | OpenAI-compatible; takes precedence if set             |
| `OPENROUTER_MODEL`   | —                           | OpenRouter slug, e.g. `anthropic/claude-sonnet-4.5`    |
| `MAX_FILE_BYTES`     | —                           | Skip full-text fetch above this size                   |

> Set **either** an Anthropic key **or** an OpenRouter key — not both. With an OpenRouter key you
> can route to OpenAI, Anthropic, Google, Llama, and more by changing `OPENROUTER_MODEL`.

If you use the [GitHub CLI](https://cli.github.com/), you can reuse its login instead of creating
a token by hand:

```bash
echo "GITHUB_TOKEN=$(gh auth token)" >> .env
```

---

## Run

```bash
source .venv/bin/activate
uvicorn backend.main:app --reload --port 8000
```

Open **http://localhost:8000**. The backend serves the front end and the API from the same origin,
so there's nothing else to start. (Use any free port you like via `--port`.)

---

## Usage

### Review a GitHub PR or commit
1. Make sure the **GitHub** source is selected.
2. Paste a URL — e.g. `https://github.com/owner/repo/pull/123` or `.../commit/<sha>`.
3. Click **Load**, then click any file to view its diff.

### Review a local branch (including uncommitted work)
1. Switch the source to **Local**.
2. Type the repository path and press **Enter** — the branch dropdowns populate.
3. Choose **base** (what to compare against — defaults to the repo's default branch) and **head**:
   - **◆ Working tree** *(default)* — your uncommitted changes (staged + unstaged + untracked).
   - **HEAD** — the current commit.
   - any local or remote branch.
4. Click **Load**.

### Ask the AI
With a diff loaded and an AI key set (Anthropic or OpenRouter), use the right-hand panel:
- **Chat** for questions, **Summary** for an overview, **Explain** for a walkthrough of the open file.

### Shortcuts
- `Alt + ←` / `Alt + →` — previous / next file
- `⛶` (toolbar) — full screen · `Esc` — exit

---

## How it works

```
backend/
  main.py      FastAPI app — serves the front end and the API
  github.py    GitHub REST fetch: PR/commit metadata, patches, lazy file contents
  gitlocal.py  Local git via subprocess: branches, merge-base diff, working-tree mode
  ai.py        Chat / summary / explain-file via Anthropic or OpenRouter
  store.py     In-memory store of loaded diffs
  models.py    Pydantic request/response models
  config.py    Settings loaded from .env
frontend/
  index.html   Monaco loaded from CDN — no build step
  css/         styles.css · fonts.css (self-hosted code fonts)
  fonts/       JetBrains Mono · Fira Code · Fantasque Sans Mono
  js/          api · diff (Monaco) · layout (Split.js) · app (orchestration)
```

- **Files load lazily** when clicked, so large PRs stay responsive.
- **AI calls go through the backend** — this keeps your provider key server-side (a browser can't
  call the API directly without leaking it and hitting CORS). With the Anthropic provider, repeated
  questions about the same diff also reuse the **prompt cache**.
- The front end reads `GET /api/config` on boot to learn whether AI is configured, and hides the
  AI pane when it isn't.
- Loaded diffs live **in memory** and reset when the server restarts.

---

## Notes & limitations

- Diff state is in-memory (single user, no database) — fine for a local tool.
- Local mode diffs *committed* state and the working tree; it does not diff arbitrary stashes.
- Binary and very large files (above `MAX_FILE_BYTES`) are skipped for full-text rendering.
- Never commit your `.env` — it's already in `.gitignore`.

---

## Contributing

Issues and pull requests are welcome. To get going:

1. Fork the repo and create a branch off `main`.
2. Follow the setup steps above and run the app locally (`uvicorn backend.main:app --reload`).
3. Keep changes focused; match the existing code style (typed Python, vanilla ES modules).
4. Open a PR describing the change and how you tested it.

---

## License

Released under the [MIT License](LICENSE). © 2026 Roberto Breve.
