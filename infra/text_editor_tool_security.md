# Text Editor tool security and operations

This app supports Anthropic `text_editor_20250728` via:

- `POST /api/projects/{project_id}/agent/bash-capable-turn`
- request flags: `allow_text_editor` and `allow_write`

Only **Owner/Editor** roles can call this endpoint.

## Core security controls

1. Disabled by default: `TEXT_EDITOR_TOOL_ENABLED=false`.
2. Read-only by default: write commands are rejected unless `allow_write=true`.
3. Path jail: all file paths are resolved under `WORKSPACE_ROOT/<project_id>`.
4. Extension allowlist: `TEXT_EDITOR_ALLOWED_EXTENSIONS`.
5. File-size guard: `TEXT_EDITOR_MAX_FILE_BYTES`.
6. Backup on write (default on): `TEXT_EDITOR_BACKUP_ENABLED=true`.
7. Audit trail (optional): `TEXT_EDITOR_AUDIT_LOG`.
8. Tool loop returns explicit `tool_result` errors for:
   - file not found / permission denied
   - multiple replacement matches
   - no replacement matches

## Tool contract

Supported commands:

- `view` (file or directory; optional `view_range`)
- `str_replace` (exactly one match required)
- `create`
- `insert`

## Operational notes

- Keep this feature off in untrusted environments.
- Prefer narrow extension allowlists in production.
- Route audit logs to centralized storage for incident response.
- Review the upstream reference for tool semantics and pricing:
  - [Anthropic Text Editor tool](https://platform.claude.com/docs/en/agents-and-tools/tool-use/text-editor-tool)
