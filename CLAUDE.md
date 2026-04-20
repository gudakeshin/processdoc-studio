# Process Doc v2 — agent onboarding

This repository is **Process Doc Studio** (FastAPI backend, Next.js frontend, multi-agent run pipeline, wiki subsystem).

## Start here

1. Read **[README.md](README.md)** for setup, environment variables, and how to run backend and frontend locally.
2. Skim **[ARCHITECTURE.md](ARCHITECTURE.md)** for the Cowork-style coordinator, sub-agents, and run lifecycle.
3. Use **[DOCUMENTATION_INDEX.md](DOCUMENTATION_INDEX.md)** to find deeper notes; historical status write-ups live under **`docs/archive/`**.

## Conventions

- Prefer existing patterns in `backend/app/api/` (auth via `get_current_user`, project scoping) and `frontend/` (`apiFetch` with bearer token).
- Do not commit **`processdoc.db`**, the **`workspace/`** tree, or generated Office binaries; they are ignored and belong on local disk or future object storage.

## Workspace rules

Project-specific AI guidance may also appear in Cursor rules; treat **`CLAUDE.md`** (this file) and **`README.md`** as the source of truth for repo-wide behavior.
