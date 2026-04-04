"""Secure file operations for Anthropic text editor tool callbacks."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from app.core.config import settings, text_editor_allowed_extensions_set
from app.services.storage import ensure_workspace, workspace_path


def _project_root(project_id: str) -> Path:
    ensure_workspace(project_id)
    return workspace_path(project_id).resolve()


def _resolve_path(project_id: str, raw_path: str) -> tuple[Path | None, str | None]:
    if not raw_path or not str(raw_path).strip():
        return None, "Error: Missing path"
    root = _project_root(project_id)
    candidate = Path(str(raw_path))
    resolved = (root / candidate).resolve() if not candidate.is_absolute() else candidate.resolve()
    try:
        resolved.relative_to(root)
    except ValueError:
        return None, "Error: Path escapes project workspace"
    return resolved, None


def _allowed_extension(path: Path) -> bool:
    suffix = path.suffix.lower()
    # extension-less files are disallowed by default
    if not suffix:
        return False
    return suffix in text_editor_allowed_extensions_set()


def _audit(operation: str, *, project_id: str, user_id: str | None, path: str, status: str, detail: str = "") -> None:
    if not settings.text_editor_audit_log:
        return
    record = {
        "ts": time.time(),
        "operation": operation,
        "project_id": project_id,
        "user_id": user_id,
        "path": path,
        "status": status,
        "detail": detail[:500],
    }
    try:
        p = Path(settings.text_editor_audit_log)
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=True) + "\n")
    except OSError:
        return


def _truncate_chars(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + f"\n\n... Output truncated ({len(text)} total chars) ..."


def _read_text_file(path: Path) -> tuple[str | None, str | None]:
    if not path.exists():
        return None, "Error: File not found"
    if not path.is_file():
        return None, "Error: Path is not a file"
    if path.stat().st_size > settings.text_editor_max_file_bytes:
        return None, f"Error: File exceeds TEXT_EDITOR_MAX_FILE_BYTES ({settings.text_editor_max_file_bytes})"
    try:
        return path.read_text(encoding="utf-8"), None
    except PermissionError:
        return None, "Error: Permission denied. Cannot read file."
    except OSError as e:
        return None, f"Error: Failed to read file: {e}"


def _backup_file(path: Path) -> None:
    if not settings.text_editor_backup_enabled or not path.exists() or not path.is_file():
        return
    stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
    backup = path.with_name(f"{path.name}.backup-{stamp}")
    backup.write_bytes(path.read_bytes())


def _view(project_id: str, raw_path: str, view_range: list[int] | None) -> tuple[str, bool]:
    resolved, err = _resolve_path(project_id, raw_path)
    if err or resolved is None:
        return (err or "Error: Invalid path"), True

    if resolved.is_dir():
        entries = sorted(resolved.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
        lines = []
        for item in entries:
            marker = "/" if item.is_dir() else ""
            lines.append(f"{item.name}{marker}")
        return (_truncate_chars("\n".join(lines), settings.text_editor_max_characters), False)

    if not _allowed_extension(resolved):
        return ("Error: File type is not allowed by TEXT_EDITOR_ALLOWED_EXTENSIONS", True)
    text, read_err = _read_text_file(resolved)
    if read_err or text is None:
        return (read_err or "Error: Cannot read file"), True

    lines = text.splitlines()
    if view_range and len(view_range) == 2:
        start, end = int(view_range[0]), int(view_range[1])
        if start < 1:
            start = 1
        if end == -1 or end > len(lines):
            end = len(lines)
        if end < start:
            end = start
        selected = lines[start - 1 : end]
        rendered = "\n".join(f"{idx}: {line}" for idx, line in enumerate(selected, start=start))
    else:
        rendered = "\n".join(f"{idx}: {line}" for idx, line in enumerate(lines, start=1))
    return (_truncate_chars(rendered, settings.text_editor_max_characters), False)


def _str_replace(project_id: str, raw_path: str, old_str: str, new_str: str, *, allow_write: bool) -> tuple[str, bool]:
    if not allow_write:
        return ("Error: Write commands disabled. Set allow_write=true for this request.", True)
    resolved, err = _resolve_path(project_id, raw_path)
    if err or resolved is None:
        return (err or "Error: Invalid path"), True
    if not _allowed_extension(resolved):
        return ("Error: File type is not allowed by TEXT_EDITOR_ALLOWED_EXTENSIONS", True)
    text, read_err = _read_text_file(resolved)
    if read_err or text is None:
        return (read_err or "Error: Cannot read file"), True
    count = text.count(old_str)
    if count == 0:
        return ("Error: No match found for replacement. Please check your text and try again.", True)
    if count > 1:
        return (f"Error: Found {count} matches for replacement text. Please provide more context to make a unique match.", True)
    updated = text.replace(old_str, new_str, 1)
    try:
        _backup_file(resolved)
        resolved.write_text(updated, encoding="utf-8")
    except PermissionError:
        return ("Error: Permission denied. Cannot write to file.", True)
    except OSError as e:
        return (f"Error: Failed to write file: {e}", True)
    return ("Successfully replaced text at exactly one location.", False)


def _create(project_id: str, raw_path: str, file_text: str, *, allow_write: bool) -> tuple[str, bool]:
    if not allow_write:
        return ("Error: Write commands disabled. Set allow_write=true for this request.", True)
    resolved, err = _resolve_path(project_id, raw_path)
    if err or resolved is None:
        return (err or "Error: Invalid path"), True
    if not _allowed_extension(resolved):
        return ("Error: File type is not allowed by TEXT_EDITOR_ALLOWED_EXTENSIONS", True)
    if len(file_text.encode("utf-8")) > settings.text_editor_max_file_bytes:
        return (f"Error: file_text exceeds TEXT_EDITOR_MAX_FILE_BYTES ({settings.text_editor_max_file_bytes})", True)
    if resolved.exists():
        return ("Error: File already exists", True)
    try:
        resolved.parent.mkdir(parents=True, exist_ok=True)
        resolved.write_text(file_text, encoding="utf-8")
    except PermissionError:
        return ("Error: Permission denied. Cannot create file.", True)
    except OSError as e:
        return (f"Error: Failed to create file: {e}", True)
    return ("Successfully created file.", False)


def _insert(project_id: str, raw_path: str, insert_line: int, insert_text: str, *, allow_write: bool) -> tuple[str, bool]:
    if not allow_write:
        return ("Error: Write commands disabled. Set allow_write=true for this request.", True)
    resolved, err = _resolve_path(project_id, raw_path)
    if err or resolved is None:
        return (err or "Error: Invalid path"), True
    if not _allowed_extension(resolved):
        return ("Error: File type is not allowed by TEXT_EDITOR_ALLOWED_EXTENSIONS", True)
    text, read_err = _read_text_file(resolved)
    if read_err or text is None:
        return (read_err or "Error: Cannot read file"), True
    lines = text.splitlines()
    at = max(0, min(int(insert_line), len(lines)))
    insert_lines = insert_text.splitlines()
    merged = lines[:at] + insert_lines + lines[at:]
    new_text = "\n".join(merged) + ("\n" if text.endswith("\n") else "")
    try:
        _backup_file(resolved)
        resolved.write_text(new_text, encoding="utf-8")
    except PermissionError:
        return ("Error: Permission denied. Cannot write to file.", True)
    except OSError as e:
        return (f"Error: Failed to write file: {e}", True)
    return ("Successfully inserted text.", False)


def execute_text_editor_tool(
    *,
    project_id: str,
    tool_input: dict[str, Any],
    allow_write: bool,
    user_id: str | None = None,
) -> tuple[str, bool]:
    """Execute Anthropic text editor tool command; returns (content, is_error)."""
    command = str(tool_input.get("command") or "").strip()
    raw_path = str(tool_input.get("path") or "").strip()
    try:
        if command == "view":
            content, is_error = _view(project_id, raw_path, tool_input.get("view_range"))
        elif command == "str_replace":
            content, is_error = _str_replace(
                project_id,
                raw_path,
                str(tool_input.get("old_str") or ""),
                str(tool_input.get("new_str") or ""),
                allow_write=allow_write,
            )
        elif command == "create":
            content, is_error = _create(
                project_id,
                raw_path,
                str(tool_input.get("file_text") or ""),
                allow_write=allow_write,
            )
        elif command == "insert":
            content, is_error = _insert(
                project_id,
                raw_path,
                int(tool_input.get("insert_line") or 0),
                str(tool_input.get("insert_text") or ""),
                allow_write=allow_write,
            )
        else:
            content, is_error = (f"Error: Unsupported text editor command '{command}'", True)
    except Exception as e:  # defensive: tool errors should return as tool_result
        content, is_error = (f"Error: text editor operation failed: {e}", True)

    _audit(
        command or "unknown",
        project_id=project_id,
        user_id=user_id,
        path=raw_path,
        status="error" if is_error else "ok",
        detail=content,
    )
    return content, is_error
