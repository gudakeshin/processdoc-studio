# Bash tool (Anthropic-aligned) — security and operations

This app can expose the [Anthropic Bash tool](https://platform.claude.com/docs/en/agents-and-tools/tool-use/bash-tool) for **Owner** and **Editor** roles only via `POST /api/projects/{project_id}/agent/bash-capable-turn`. **Viewers cannot invoke it.**

## Threat model

- The model may request shell commands; the **server executes** them under a project sandbox (`WORKSPACE_ROOT/<project_id>/bash_sandbox`).
- Treat this as **remote code execution** risk: enable only in trusted environments with monitoring.

## Required controls (v1)

1. **Off by default:** `BASH_TOOL_ENABLED=false` until explicitly enabled.
2. **Explicit client opt-in:** `allow_bash: true` on each request; server still requires `BASH_TOOL_ENABLED=true`.
3. **Workspace jail:** Commands run with `cwd` under the project sandbox; `cd` cannot escape (path resolved and checked against sandbox root).
4. **Operator filtering:** By default (`BASH_FORBID_OPERATORS=true`), chaining, pipes, redirections, and `$(...)`-style substitution are rejected.
5. **Optional command allowlist:** `BASH_ALLOWLIST_ENABLED=true` with `BASH_ALLOWLIST_COMMANDS` (comma-separated basenames).
6. **Timeouts:** `BASH_COMMAND_TIMEOUT_SEC` per subprocess; `BASH_SESSION_TIMEOUT_SEC` for idle session expiry.
7. **Output limits:** `BASH_MAX_OUTPUT_BYTES` / `BASH_MAX_OUTPUT_LINES` with truncation.
8. **Audit log:** Set `BASH_AUDIT_LOG` to a file path; append JSON lines (command preview, outcome, output hash — no raw secrets).
9. **Rate limit:** `BASH_RATE_LIMIT_PER_MINUTE` per authenticated user (in-memory counter).
10. **Docker (optional):** `BASH_DOCKER_ENABLED=true` runs each command in `docker run --network none` with the sandbox mounted read-write at `/work`; sessions do not persist `cd` across commands in Docker mode.

## Observability

- Counters: `bash_tool_calls_total`, `bash_tool_failures_total`, `bash_tool_timeouts_total` (see `/metrics`).
- Health: `GET /api/health/bash-tool`.

## Operational recommendations

- Run API workers as a **low-privilege** OS user; do not mount host secrets into the process.
- Prefer **allowlist** mode for production; expand binaries deliberately.
- Point `BASH_AUDIT_LOG` to a tamper-evident or centralized log sink in production.
- Review Anthropic **tool pricing** (bash adds input tokens per their docs).

## Internal API

Python code can call `run_claude_bash_tool_loop(...)` from `app.services.claude_tools`; keep `allow_bash=False` unless both policy and `BASH_TOOL_ENABLED` permit it.
