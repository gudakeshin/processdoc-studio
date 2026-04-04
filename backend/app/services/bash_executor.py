"""Sandboxed Bash execution for Anthropic-style bash tool callbacks."""

from __future__ import annotations

import hashlib
import json
import logging
import re
import shlex
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.core.config import bash_allowlist_set, settings
from app.services.storage import ensure_workspace, workspace_path

_LOG = logging.getLogger(__name__)

# Reject command strings containing these substrings (first line of defense).
_RAW_FORBIDDEN = re.compile(
    r"[\n\r;]|&&|\|\||\||`|\$\(|\${|>>|>|<<|<\(|>\(|`\s*&&"
)
_SHELL_OPERATOR_TOKENS = frozenset({"&&", "||", "|", ";", "&", ">", "<", ">>", "2>", "2>>", "&>", "|&"})


def _sandbox_root(project_id: str) -> Path:
    ensure_workspace(project_id)
    root = workspace_path(project_id) / "bash_sandbox"
    root.mkdir(parents=True, exist_ok=True)
    return root.resolve()


def sanitize_output(text: str, max_bytes: int | None = None) -> str:
    """Redact common secret patterns and cap size."""
    if not text:
        return text
    out = text
    patterns = [
        (re.compile(r"(?i)(api[_-]?key|secret|token|password|bearer)\s*[=:]\s*\S+"), r"\1=***"),
        (re.compile(r"(?i)aws_(access_key_id|secret_access_key)\s*=\s*\S+"), r"aws_\1=***"),
        (re.compile(r"(?i)(sk-[a-zA-Z0-9]{20,})"), r"sk-***"),
    ]
    for rx, rep in patterns:
        out = rx.sub(rep, out)
    limit = max_bytes if max_bytes is not None else settings.bash_max_output_bytes
    if len(out.encode("utf-8", errors="replace")) > limit:
        enc = out.encode("utf-8", errors="replace")[:limit]
        out = enc.decode("utf-8", errors="replace") + f"\n\n... truncated at {limit} bytes"
    lines = out.splitlines()
    cap = settings.bash_max_output_lines
    if len(lines) > cap:
        out = "\n".join(lines[:cap]) + f"\n\n... truncated ({len(lines)} lines total)"
    return out


def _audit_line(
    *,
    project_id: str,
    user_id: str | None,
    session_id: str,
    command: str,
    outcome: str,
    output_digest: str,
) -> None:
    if not settings.bash_audit_log:
        return
    try:
        path = Path(settings.bash_audit_log)
        path.parent.mkdir(parents=True, exist_ok=True)
        rec = {
            "ts": time.time(),
            "project_id": project_id,
            "user_id": user_id,
            "session_id": session_id,
            "command": command[:2000],
            "outcome": outcome,
            "output_sha256": output_digest,
        }
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=True, default=_json_default) + "\n")
    except OSError as e:
        _LOG.warning("bash audit write failed: %s", e)


def _json_default(obj: Any) -> str:
    return str(obj)


def validate_command(command: str) -> tuple[bool, str]:
    if not command or not command.strip():
        return False, "empty command"
    s = command.strip()
    if settings.bash_forbid_operators:
        if _RAW_FORBIDDEN.search(s):
            return False, "shell chaining, redirections, or command substitution are not allowed"
        try:
            tokens = shlex.split(s, posix=True)
        except ValueError as e:
            return False, f"could not parse command: {e}"
        for t in tokens:
            if t in _SHELL_OPERATOR_TOKENS:
                return False, f"operator token not allowed: {t}"
            if t.startswith("$") or "`" in t:
                return False, "variable substitution or backticks not allowed"
    else:
        try:
            tokens = shlex.split(s, posix=True)
        except ValueError as e:
            return False, f"could not parse command: {e}"
    if not tokens:
        return False, "empty after parse"
    if settings.bash_allowlist_enabled:
        allow = bash_allowlist_set()
        exe = tokens[0].split("/")[-1].lower()
        if exe not in allow:
            return False, f"command not in allowlist: {exe}"
    return True, ""


@dataclass
class _Session:
    cwd: Path
    created: float = field(default_factory=time.time)
    touched: float = field(default_factory=time.time)


class BashExecutor:
    """Per-project sandboxes under workspace/<pid>/bash_sandbox; optional Docker one-shot mode."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sessions: dict[str, _Session] = {}

    def _get_session(self, session_id: str, project_id: str) -> _Session:
        root = _sandbox_root(project_id)
        with self._lock:
            sess = self._sessions.get(session_id)
            now = time.time()
            if sess:
                if now - sess.created > settings.bash_session_timeout_sec:
                    sess = None
                else:
                    sess.touched = now
            if not sess:
                self._sessions[session_id] = _Session(cwd=root)
                sess = self._sessions[session_id]
            return sess

    def restart_session(self, session_id: str, project_id: str) -> None:
        root = _sandbox_root(project_id)
        with self._lock:
            self._sessions[session_id] = _Session(cwd=root)

    def _resolve_under_sandbox(self, path: Path, sandbox: Path) -> Path | None:
        try:
            resolved = path.resolve()
            resolved.relative_to(sandbox)
            return resolved
        except ValueError:
            return None

    def _handle_cd(self, arg: str | None, session: _Session, sandbox: Path) -> tuple[bool, str]:
        if not arg or arg.strip() == "~":
            session.cwd = sandbox
            return True, ""
        target = (session.cwd / arg).resolve()
        ok = self._resolve_under_sandbox(target, sandbox)
        if not ok:
            return False, f"cd: path escapes sandbox or invalid: {arg}\n"
        if not ok.exists() or not ok.is_dir():
            return False, f"cd: not a directory: {arg}\n"
        session.cwd = ok
        return True, ""

    def execute(
        self,
        *,
        project_id: str,
        session_id: str,
        command: str | None,
        restart: bool,
        user_id: str | None,
    ) -> tuple[str, bool]:
        """Returns (stdout/stderr combined text, is_error)."""
        sandbox = _sandbox_root(project_id)
        digest = hashlib.sha256(b"").hexdigest()

        if restart:
            self.restart_session(session_id, project_id)
            msg = "Bash session restarted; cwd reset to sandbox root."
            digest = hashlib.sha256(msg.encode()).hexdigest()
            _audit_line(
                project_id=project_id,
                user_id=user_id,
                session_id=session_id,
                command="<restart>",
                outcome="restart",
                output_digest=digest,
            )
            return msg + "\n", False

        if command is None:
            _audit_line(
                project_id=project_id,
                user_id=user_id,
                session_id=session_id,
                command="<none>",
                outcome="reject",
                output_digest=digest,
            )
            return "Error: missing command\n", True

        session = self._get_session(session_id, project_id)
        cmd_strip = command.strip()
        if cmd_strip.startswith("cd ") or cmd_strip == "cd":
            rest = cmd_strip[2:].strip() if cmd_strip.startswith("cd ") else ""
            ok, err_out = self._handle_cd(rest or None, session, sandbox)
            digest = hashlib.sha256(err_out.encode()).hexdigest()
            _audit_line(
                project_id=project_id,
                user_id=user_id,
                session_id=session_id,
                command=command[:2000],
                outcome="cd_ok" if ok else "cd_error",
                output_digest=digest,
            )
            return err_out if not ok else "", False

        ok, reason = validate_command(command)
        if not ok:
            _audit_line(
                project_id=project_id,
                user_id=user_id,
                session_id=session_id,
                command=command[:2000],
                outcome=f"reject:{reason}",
                output_digest=digest,
            )
            return f"Error: {reason}\n", True

        try:
            session.cwd.resolve().relative_to(sandbox)
        except ValueError:
            session.cwd = sandbox

        if settings.bash_docker_enabled:
            out, err_flag = self._run_docker(command, sandbox)
        else:
            out, err_flag = self._run_subprocess(command, session.cwd)

        out = sanitize_output(out)
        digest = hashlib.sha256(out.encode("utf-8", errors="replace")).hexdigest()
        _audit_line(
            project_id=project_id,
            user_id=user_id,
            session_id=session_id,
            command=command[:2000],
            outcome="timeout" if err_flag and "timed out" in out.lower() else ("error" if err_flag else "ok"),
            output_digest=digest,
        )
        return out, err_flag

    def _run_subprocess(self, command: str, cwd: Path) -> tuple[str, bool]:
        try:
            proc = subprocess.run(
                ["/bin/bash", "-c", command],
                cwd=str(cwd),
                capture_output=True,
                text=True,
                timeout=settings.bash_command_timeout_sec,
                env=_minimal_env(),
            )
            combined = (proc.stdout or "") + (proc.stderr or "")
            return combined, proc.returncode != 0
        except subprocess.TimeoutExpired:
            return f"Error: command timed out after {settings.bash_command_timeout_sec}s\n", True
        except OSError as e:
            return f"Error: execution failed: {e}\n", True

    def _run_docker(self, command: str, sandbox: Path) -> tuple[str, bool]:
        docker = _find_docker()
        if not docker:
            return "Error: BASH_DOCKER_ENABLED but docker CLI not found\n", True
        try:
            run_args = [
                docker,
                "run",
                "-i",
                "--rm",
                "--network",
                "none",
            ]
            seccomp = str(getattr(settings, "bash_docker_seccomp_profile", "") or "").strip()
            if seccomp:
                run_args.extend(["--security-opt", f"seccomp={seccomp}"])
            run_args.extend(
                [
                    "-v",
                    f"{sandbox}:/work:rw",
                    "-w",
                    "/work",
                    settings.bash_docker_image,
                    "sh",
                    "-c",
                    command,
                ]
            )
            proc = subprocess.run(
                run_args,
                capture_output=True,
                text=True,
                timeout=settings.bash_command_timeout_sec,
            )
            combined = (proc.stdout or "") + (proc.stderr or "")
            return combined, proc.returncode != 0
        except subprocess.TimeoutExpired:
            return f"Error: command timed out after {settings.bash_command_timeout_sec}s\n", True
        except OSError as e:
            return f"Error: docker failed: {e}\n", True


def _find_docker() -> str | None:
    import shutil

    return shutil.which("docker")


def _minimal_env() -> dict[str, str]:
    keep = {"PATH", "HOME", "LANG", "LC_ALL", "USER"}
    return {k: v for k, v in dict(__import__("os").environ).items() if k in keep and v}


_executor: BashExecutor | None = None


def get_bash_executor() -> BashExecutor:
    global _executor
    if _executor is None:
        _executor = BashExecutor()
    return _executor


def new_session_id() -> str:
    return str(uuid.uuid4())
