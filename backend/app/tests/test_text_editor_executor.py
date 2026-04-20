from pathlib import Path

import pytest

from app.core.config import Settings
from app.services.text_editor_executor import execute_text_editor_tool

_TEST_SETTINGS_BASE = {
    "jwt_secret": "test-jwt-secret-min-16chars",
    "database_url": "sqlite:///:memory:",
}


def _patch_cfg(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Settings:
    cfg = Settings(
        **_TEST_SETTINGS_BASE,
        workspace_root=str(tmp_path),
        text_editor_tool_enabled=True,
        text_editor_allowed_extensions=".py,.md,.txt,.json",
        text_editor_backup_enabled=True,
        text_editor_max_file_bytes=1024 * 1024,
    )
    monkeypatch.setattr("app.services.text_editor_executor.settings", cfg)
    monkeypatch.setattr("app.services.storage.settings", cfg)
    return cfg


def test_path_traversal_rejected(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _patch_cfg(monkeypatch, tmp_path)
    content, is_error = execute_text_editor_tool(
        project_id="p1",
        tool_input={"command": "view", "path": "../outside.txt"},
        allow_write=False,
        user_id="u1",
    )
    assert is_error is True
    assert "escapes" in content


def test_view_range(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _patch_cfg(monkeypatch, tmp_path)
    base = tmp_path / "p2"
    base.mkdir(parents=True, exist_ok=True)
    f = base / "a.py"
    f.write_text("a\nb\nc\nd\n", encoding="utf-8")
    content, is_error = execute_text_editor_tool(
        project_id="p2",
        tool_input={"command": "view", "path": "a.py", "view_range": [2, 3]},
        allow_write=False,
        user_id="u1",
    )
    assert is_error is False
    assert "2: b" in content
    assert "3: c" in content
    assert "1: a" not in content


def test_str_replace_match_modes(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _patch_cfg(monkeypatch, tmp_path)
    base = tmp_path / "p3"
    base.mkdir(parents=True, exist_ok=True)
    f = base / "b.py"
    f.write_text("x\nx\n", encoding="utf-8")

    no_match, no_err = execute_text_editor_tool(
        project_id="p3",
        tool_input={"command": "str_replace", "path": "b.py", "old_str": "z", "new_str": "y"},
        allow_write=True,
        user_id="u1",
    )
    assert no_err is True
    assert "No match found" in no_match

    multi_match, multi_err = execute_text_editor_tool(
        project_id="p3",
        tool_input={"command": "str_replace", "path": "b.py", "old_str": "x", "new_str": "y"},
        allow_write=True,
        user_id="u1",
    )
    assert multi_err is True
    assert "Found 2 matches" in multi_match

    f.write_text("x\nz\n", encoding="utf-8")
    ok, ok_err = execute_text_editor_tool(
        project_id="p3",
        tool_input={"command": "str_replace", "path": "b.py", "old_str": "x", "new_str": "y"},
        allow_write=True,
        user_id="u1",
    )
    assert ok_err is False
    assert "Successfully replaced" in ok
    assert f.read_text(encoding="utf-8").startswith("y")


def test_write_rejected_by_default(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _patch_cfg(monkeypatch, tmp_path)
    base = tmp_path / "p4"
    base.mkdir(parents=True, exist_ok=True)
    f = base / "c.py"
    f.write_text("x\n", encoding="utf-8")
    content, is_error = execute_text_editor_tool(
        project_id="p4",
        tool_input={"command": "str_replace", "path": "c.py", "old_str": "x", "new_str": "y"},
        allow_write=False,
        user_id="u1",
    )
    assert is_error is True
    assert "allow_write=true" in content


def test_backup_created_on_write(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _patch_cfg(monkeypatch, tmp_path)
    base = tmp_path / "p5"
    base.mkdir(parents=True, exist_ok=True)
    f = base / "d.py"
    f.write_text("alpha\n", encoding="utf-8")
    _, is_error = execute_text_editor_tool(
        project_id="p5",
        tool_input={"command": "str_replace", "path": "d.py", "old_str": "alpha", "new_str": "beta"},
        allow_write=True,
        user_id="u1",
    )
    assert is_error is False
    backups = list(base.glob("d.py.backup-*"))
    assert backups, "expected backup file"
