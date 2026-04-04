from pathlib import Path
from unittest import mock

import pytest

from app.core.config import Settings
from app.services.bash_executor import BashExecutor, sanitize_output, validate_command


def test_validate_command_rejects_chaining() -> None:
    ok, msg = validate_command("echo a && echo b")
    assert ok is False
    assert "not allowed" in msg


def test_validate_command_accepts_simple() -> None:
    ok, msg = validate_command("echo hello")
    assert ok is True
    assert msg == ""


def test_sanitize_output_truncates_lines() -> None:
    long = "\n".join([f"line {i}" for i in range(500)])
    with mock.patch("app.services.bash_executor.settings") as s:
        s.bash_max_output_bytes = 1_000_000
        s.bash_max_output_lines = 50
        out = sanitize_output(long)
        assert "truncated" in out


def test_execute_echo(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    cfg = Settings(
        workspace_root=str(tmp_path),
        jwt_secret="test",
        bash_tool_enabled=True,
        bash_command_timeout_sec=30,
    )
    monkeypatch.setattr("app.services.bash_executor.settings", cfg)
    monkeypatch.setattr("app.services.storage.settings", cfg)
    pid = "proj_exec"
    ex = BashExecutor()
    out, err = ex.execute(project_id=pid, session_id="s1", command="echo hello", restart=False, user_id=None)
    assert err is False
    assert "hello" in out


def test_cd_rejects_escape(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    cfg = Settings(workspace_root=str(tmp_path), jwt_secret="test", bash_tool_enabled=True)
    monkeypatch.setattr("app.services.bash_executor.settings", cfg)
    monkeypatch.setattr("app.services.storage.settings", cfg)
    pid = "proj_cd"
    ex = BashExecutor()
    out, err = ex.execute(project_id=pid, session_id="s2", command="cd /etc", restart=False, user_id=None)
    assert err is False
    assert "escapes" in out or "not a directory" in out
