# Security operations checklist

Use this list when onboarding, rotating credentials, or auditing deployments.

## Secrets

- Keep `.env` and `frontend/.env.local` out of version control (root `.gitignore` already lists `.env`).
- Rotate **Anthropic** or other third-party API keys if they may have been exposed (logs, screenshots, support tickets).
- Use strong `JWT_SECRET` in production; never ship the development default.

## Agent tools (optional)

When `BASH_TOOL_ENABLED` or `TEXT_EDITOR_TOOL_ENABLED` is set, review:

- [infra/bash_tool_security.md](bash_tool_security.md)
- [infra/text_editor_tool_security.md](text_editor_tool_security.md)

Confirm role restrictions on the agent API (`Owner` / `Editor`) and explicit client opt-in flags (`allow_bash`, `allow_text_editor`, `allow_write`).

## Dependency and runtime hygiene

- Prefer pinned images and least-privilege users for any Docker-based Bash execution.
- Review Redis and database URLs; restrict network access in production.
- CI runs **`pip-audit`** (backend) and **`npm audit --audit-level=high`** (frontend); [Dependabot](../.github/dependabot.yml) opens weekly update PRs for GitHub Actions, pip, and npm.

## API and browser-facing risks

- **CORS:** The API uses `CORSMiddleware` with `allow_credentials=True`. Keep `CORS_ORIGINS` to an explicit allowlist in production—wildcard or overly broad origins combined with credentials increase impact of misconfiguration.
- **JWT in query strings:** SSE and some WebSocket clients pass `?token=` because `EventSource` cannot set headers. Treat URLs as sensitive (avoid logging full query strings; configure proxies not to cache these URLs; be aware of Referer leakage to third parties).
- **Tokens in `localStorage`:** The SPA stores access/refresh tokens in the browser. Reduce XSS risk with a strict **Content Security Policy**, dependency updates, and careful handling of untrusted HTML/markdown.
- **High-risk tools:** Keep `BASH_TOOL_ENABLED` / `MCP_ENABLED` off in production unless required; see agent tool docs above.
