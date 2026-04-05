"""Swarm orchestration: task DAG, teams, teammate workspaces, messaging."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime
import logging
import subprocess
from pathlib import Path
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import RunTask, SwarmMessage, SwarmTeam, SwarmTeammate
from app.services.observability import increment

_LOG = logging.getLogger(__name__)

# Worker preamble fragment for subagent system prompts (guide best practice).
SWARM_WORKER_PREAMBLE = (
    "You are a WORKER teammate in a swarm: pick up assigned tasks, use tools, report completion. "
    "Do not spawn sub-agents or delegate to other orchestrators. If blocked, report a clear blocker."
)


def enrich_run_todos_with_dependencies(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Attach depends_on (task ids) to milestone rows for DAG semantics."""
    out: list[dict[str, Any]] = []
    out_ids = [str(r.get("id") or "") for r in rows if str(r.get("id") or "").startswith("out:")]
    for r in rows:
        row = dict(r)
        rid = str(row.get("id") or "").strip()
        deps: list[str] = []
        if rid == "context":
            deps = []
        elif rid == "process_model":
            deps = ["context"]
        elif rid == "plan":
            deps = ["process_model"]
        elif rid.startswith("out:"):
            deps = ["plan"]
        elif rid == "qa":
            deps = list(out_ids) if out_ids else ["plan"]
        elif rid == "guardrails":
            deps = ["qa"]
        elif rid == "visual_qa":
            deps = ["guardrails"]
        elif rid == "finalize":
            deps = ["visual_qa"]
        row["depends_on"] = deps
        out.append(row)
    return out


def _normalize_dep_ids(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    return [str(x).strip() for x in raw if str(x).strip()]


def validate_task_dag(task_ids: Iterable[str], depends_map: dict[str, list[str]]) -> tuple[bool, str | None]:
    """
    Validate task DAG for missing dependencies and cycles.

    Args:
        task_ids: Iterable of task IDs
        depends_map: Dict mapping task_id to list of dependency task_ids

    Returns:
        Tuple of (is_valid, error_message)
    """
    ids = set(task_ids)

    # Check for missing dependencies
    for tid, deps in depends_map.items():
        if tid not in ids:
            continue
        for d in deps:
            if d not in ids:
                return False, f"Task {tid!r} depends on unknown task {d!r}"

    # Check for cycles using DFS
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str) -> bool:
        """Return True if cycle found."""
        if node in visited:
            return False
        if node in visiting:
            return True  # Cycle detected
        visiting.add(node)
        for d in depends_map.get(node, []):
            if d in ids and visit(d):
                return True
        visiting.remove(node)
        visited.add(node)
        return False

    for tid in ids:
        if tid not in visited and visit(tid):
            return False, "Task graph contains a cycle"

    return True, None


def validate_task_dag_from_run_tasks(tasks: list[RunTask]) -> tuple[bool, str | None]:
    """
    Validate task DAG from RunTask objects.

    Args:
        tasks: List of RunTask objects

    Returns:
        Tuple of (is_valid, error_message)
    """
    task_ids = [t.id for t in tasks]
    depends_map = {}

    for task in tasks:
        try:
            deps = json.loads(task.depends_on_json or "[]")
            if not isinstance(deps, list):
                return False, f"Task {task.id!r} has invalid depends_on_json (not a list)"
            depends_map[task.id] = deps
        except json.JSONDecodeError as e:
            return False, f"Task {task.id!r} has invalid JSON in depends_on_json: {e}"

    return validate_task_dag(task_ids, depends_map)


def ready_task_ids(tasks: list[RunTask]) -> list[str]:
    """Task ids that are queued/blocked-for-deps with all dependencies terminal."""
    terminal = {"completed", "skipped", "failed"}
    by_id = {t.id: t for t in tasks}
    deps_of: dict[str, list[str]] = {}
    for t in tasks:
        try:
            deps_of[t.id] = json.loads(t.depends_on_json or "[]")
        except json.JSONDecodeError:
            deps_of[t.id] = []
        if not isinstance(deps_of[t.id], list):
            deps_of[t.id] = []

    ready: list[str] = []
    for t in tasks:
        if t.status not in {"queued", "blocked"}:
            continue
        ok = True
        for d in deps_of.get(t.id, []):
            dep = by_id.get(d)
            if dep is None or dep.status not in terminal:
                ok = False
                break
        if ok:
            ready.append(t.id)
    return ready


def ensure_swarm_team(session: Session, *, project_id: str, run_id: str) -> SwarmTeam:
    existing = session.scalar(select(SwarmTeam).where(SwarmTeam.run_id == run_id))
    if existing:
        ensure_teammate_workspace_dirs(session=session, project_id=project_id, run_id=run_id)
        return existing
    team = SwarmTeam(
        id=_new_id(),
        run_id=run_id,
        project_id=project_id,
        name="default",
        status="active",
        created_at=datetime.utcnow(),
    )
    session.add(team)
    session.flush()
    for i, slug in enumerate(("teammate-1", "teammate-2", "teammate-3")):
        session.add(
            SwarmTeammate(
                id=_new_id(),
                team_id=team.id,
                teammate_id=slug,
                role="worker" if i else "lead",
                status="idle",
                created_at=datetime.utcnow(),
            )
        )
    session.flush()
    ensure_teammate_workspace_dirs(session=session, project_id=project_id, run_id=run_id)
    return team


def _new_id() -> str:
    return uuid.uuid4().hex[:16]


def list_teammates(session: Session, *, run_id: str) -> list[SwarmTeammate]:
    team = session.scalar(select(SwarmTeam).where(SwarmTeam.run_id == run_id))
    if not team:
        return []
    return list(session.scalars(select(SwarmTeammate).where(SwarmTeammate.team_id == team.id)).all())


def send_swarm_message(
    session: Session,
    *,
    run_id: str,
    project_id: str,
    from_teammate: str,
    body: str,
    to_teammate: str | None = None,
    team_id: str | None = None,
    correlation_id: str | None = None,
) -> SwarmMessage:
    msg = SwarmMessage(
        id=_new_id(),
        run_id=run_id,
        team_id=team_id,
        from_teammate=from_teammate,
        to_teammate=to_teammate,
        body=body[:16000],
        correlation_id=correlation_id,
        created_at=datetime.utcnow(),
        read_at=None,
    )
    session.add(msg)
    session.flush()
    return msg


def list_swarm_messages(session: Session, *, run_id: str, limit: int = 200) -> list[SwarmMessage]:
    return list(
        session.scalars(
            select(SwarmMessage).where(SwarmMessage.run_id == run_id).order_by(SwarmMessage.created_at.desc()).limit(limit)
        ).all()
    )


def serialize_message(m: SwarmMessage) -> dict[str, Any]:
    return {
        "id": m.id,
        "run_id": m.run_id,
        "team_id": m.team_id,
        "from_teammate": m.from_teammate,
        "to_teammate": m.to_teammate,
        "body": m.body,
        "correlation_id": m.correlation_id,
        "created_at": m.created_at.isoformat() if m.created_at else None,
        "read_at": m.read_at.isoformat() if m.read_at else None,
    }


def persist_instruction_broadcast_swarm_event_payload(
    session: Session,
    *,
    project_id: str,
    run_id: str,
    instruction: str,
    from_teammate: str = "user",
) -> dict[str, Any] | None:
    """When swarm orchestration is enabled, persist a broadcast SwarmMessage for the run instruction.

    Returns a payload suitable for ``append_run_event(..., \"swarm_message\", payload)`` with
    ``broadcast: True``. Returns ``None`` if swarm is disabled or instruction is empty.
    """
    from app.core.config import settings

    if not bool(getattr(settings, "swarm_orchestration_enabled", False)):
        return None
    text = (instruction or "").strip()
    if not text:
        return None
    body = f"Run instruction:\n{text[:15000]}"
    team = ensure_swarm_team(session, project_id=project_id, run_id=run_id)
    msg = send_swarm_message(
        session,
        run_id=run_id,
        project_id=project_id,
        from_teammate=(from_teammate or "user").strip() or "user",
        body=body,
        to_teammate=None,
        team_id=team.id,
    )
    payload = serialize_message(msg)
    increment("swarm_instruction_broadcast_on_start_total")
    return {**payload, "broadcast": True}


def format_swarm_mailbox_for_teammate(*, run_id: str, teammate_id: str, limit: int = 20) -> str:
    """Recent messages visible to this teammate: broadcasts, DMs to them, and DMs they sent."""
    from app.db.session import SessionLocal

    tm = str(teammate_id or "").strip()
    rid = str(run_id or "").strip()
    if not rid or not tm:
        return ""
    db = SessionLocal()
    try:
        rows = list_swarm_messages(db, run_id=rid, limit=max(limit * 4, 80))
    finally:
        db.close()
    visible: list[SwarmMessage] = []
    for m in rows:
        to = (m.to_teammate or "").strip()
        if not to:
            visible.append(m)
        elif to == tm:
            visible.append(m)
        elif (m.from_teammate or "").strip() == tm and to:
            visible.append(m)
    visible = list(reversed(visible[-limit:]))
    if not visible:
        return ""
    lines: list[str] = []
    for m in visible:
        to = (m.to_teammate or "").strip()
        tag = "broadcast" if not to else f"to:{to}"
        body = (m.body or "").replace("\n", " ")[:500]
        lines.append(f"- [{tag}] {m.from_teammate}: {body}")
    return "## Team mailbox (recent)\n" + "\n".join(lines) + "\n"


def teammate_workspace_dir(project_id: str, run_id: str, teammate_id: str) -> Path:
    """Project-scoped teammate sandbox: {workspace_root}/{project_id}/swarm/{run}/teammates/{id}."""
    from app.services.storage import workspace_path

    base = workspace_path(project_id).resolve()
    safe_run = "".join(c for c in run_id if c.isalnum() or c in "-_")[:64]
    safe_tm = "".join(c for c in teammate_id if c.isalnum() or c in "-_")[:64]
    return base / "swarm" / safe_run / "teammates" / safe_tm


def ensure_teammate_workspace_dirs(*, session: Session, project_id: str, run_id: str) -> None:
    """Create on-disk sandboxes for each logical teammate (and optional git worktrees)."""
    from app.core.config import settings

    mates = list_teammates(session, run_id=run_id)
    if not mates:
        return
    if bool(getattr(settings, "swarm_git_worktrees_enabled", False)):
        _maybe_create_git_worktrees(project_id=project_id, run_id=run_id, teammates=mates)
        return
    for m in mates:
        teammate_workspace_dir(project_id, run_id, m.teammate_id).mkdir(parents=True, exist_ok=True)


def _project_git_root(project_id: str) -> Path | None:
    from app.services.storage import workspace_path

    root = workspace_path(project_id).resolve()
    if (root / ".git").exists():
        return root
    return None


def _maybe_create_git_worktrees(
    *,
    project_id: str,
    run_id: str,
    teammates: list[SwarmTeammate],
) -> None:
    proj_root = _project_git_root(project_id)
    if proj_root is None:
        for m in teammates:
            teammate_workspace_dir(project_id, run_id, m.teammate_id).mkdir(parents=True, exist_ok=True)
        return
    safe_run = "".join(c for c in run_id if c.isalnum() or c in "-_")[:64]
    for m in teammates:
        wd = teammate_workspace_dir(project_id, run_id, m.teammate_id)
        if wd.exists() and any(wd.iterdir()):
            continue
        wd.parent.mkdir(parents=True, exist_ok=True)
        safe_tm = "".join(c for c in m.teammate_id if c.isalnum() or c in "-_")[:48]
        branch = f"pd-swarm-{safe_run}-{safe_tm}"[:60]
        try:
            proc = subprocess.run(
                [
                    "git",
                    "-C",
                    str(proj_root),
                    "worktree",
                    "add",
                    "-b",
                    branch,
                    str(wd),
                    "HEAD",
                ],
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )
            if proc.returncode != 0:
                _LOG.warning("git worktree add failed for %s: %s", wd, (proc.stderr or proc.stdout or "")[:500])
                wd.mkdir(parents=True, exist_ok=True)
        except Exception as exc:  # noqa: BLE001
            _LOG.warning("git worktree add error for %s: %s", wd, exc)
            wd.mkdir(parents=True, exist_ok=True)


def ensure_path_within_teammate_workspace(project_id: str, run_id: str, teammate_id: str, candidate: str | Path) -> Path:
    root = teammate_workspace_dir(project_id, run_id, teammate_id).resolve()
    path = Path(candidate).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError("Path escapes teammate workspace") from exc
    return path


@dataclass
class LeadPlanResult:
    tasks: list[dict[str, Any]]
    rationale: str
    used_llm: bool


def deterministic_lead_task_graph(*, wanted: list[str], milestone_labels: dict[str, str] | None = None) -> LeadPlanResult:
    """Build a task graph from output types (no LLM)."""
    from app.services.run_todo_snapshot import build_run_todo_rows

    rows = build_run_todo_rows(wanted, milestone_labels=milestone_labels)
    enriched = enrich_run_todos_with_dependencies([dict(r) for r in rows])
    return LeadPlanResult(tasks=enriched, rationale="Deterministic pipeline from requested outputs.", used_llm=False)


def lead_plan_with_optional_llm(
    *,
    wanted: list[str],
    milestone_labels: dict[str, str] | None = None,
) -> LeadPlanResult:
    """Deterministic pipeline plus optional LLM `extra_tasks` merged on top (DAG-validated)."""
    from app.core.config import settings
    from app.services.claude import _extract_first_json_object, claude_generate, is_claude_enabled

    base = deterministic_lead_task_graph(wanted=wanted, milestone_labels=milestone_labels)
    if not bool(getattr(settings, "swarm_llm_lead_enabled", False)) or not is_claude_enabled():
        return base

    existing_ids = {str(t.get("id") or "").strip() for t in base.tasks if str(t.get("id") or "").strip()}
    prompt = (
        "You extend a document-generation run task graph. Return a single JSON object only, no markdown fences.\n"
        'Schema: {"extra_tasks": ['
        '{"id": string, "title": string, "description"?: string, "depends_on": string[], '
        '"phase"?: string, "assigned_teammate_id"?: string}'
        "]}\n"
        "Rules: ids must be unique and MUST NOT duplicate any existing_task_ids. "
        "depends_on entries must reference only ids from existing_task_ids or new extra task ids. "
        "Use phase \"custom\" for human or coordinator-follow-up work.\n"
        f"existing_task_ids: {sorted(existing_ids)}\n"
        f"wanted_outputs: {wanted}\n"
    )
    try:
        text = claude_generate(
            system="You output only valid minified JSON for task orchestration.",
            user=prompt,
            max_tokens=min(8192, int(getattr(settings, "subagent_tool_max_tokens", 8192) or 8192)),
        )
        obj = _extract_first_json_object(text)
        extras_raw = obj.get("extra_tasks") if isinstance(obj, dict) else None
        if not isinstance(extras_raw, list):
            return LeadPlanResult(
                tasks=base.tasks,
                rationale=base.rationale + " LLM returned no extra_tasks array; using deterministic plan only.",
                used_llm=False,
            )
        extras: list[dict[str, Any]] = []
        for item in extras_raw:
            if not isinstance(item, dict):
                continue
            tid = str(item.get("id") or "").strip()
            title = str(item.get("title") or "").strip()
            if not tid or not title:
                continue
            if tid in existing_ids:
                continue
            deps = item.get("depends_on")
            dep_list = [str(x).strip() for x in deps] if isinstance(deps, list) else []
            phase = str(item.get("phase") or "custom")[:16]
            desc = item.get("description")
            assign = item.get("assigned_teammate_id")
            row: dict[str, Any] = {
                "id": tid,
                "label": title,
                "title": title,
                "status": "pending",
                "depends_on": dep_list,
                "phase": phase,
            }
            if desc is not None:
                row["description"] = str(desc)
            if assign is not None and str(assign).strip():
                row["assigned_teammate_id"] = str(assign).strip()
            extras.append(row)
            existing_ids.add(tid)
        merged = [dict(x) for x in base.tasks] + extras
        id_set = {str(t.get("id") or "").strip() for t in merged if str(t.get("id") or "").strip()}
        depends_map: dict[str, list[str]] = {}
        for t in merged:
            tid = str(t.get("id") or "").strip()
            if not tid:
                continue
            d = t.get("depends_on")
            depends_map[tid] = [str(x).strip() for x in d] if isinstance(d, list) else []
        validate_task_dag(id_set, depends_map)
        return LeadPlanResult(
            tasks=merged,
            rationale=base.rationale + f" Merged {len(extras)} LLM extra task(s).",
            used_llm=True,
        )
    except Exception as exc:  # noqa: BLE001
        _LOG.warning("lead_plan LLM merge failed: %s", exc)
        return LeadPlanResult(
            tasks=base.tasks,
            rationale=base.rationale + f" LLM lead merge failed ({str(exc)[:120]}); deterministic plan only.",
            used_llm=False,
        )


def promote_teammate_artifacts(
    *,
    project_id: str,
    run_id: str,
    teammate_id: str,
    relative_paths: list[str],
    canonical_subdir: str = "promoted",
) -> tuple[list[str], list[str]]:
    """
    Copy paths from a teammate sandbox into {project}/swarm/{run}/promoted/.
    Returns (promoted_paths, conflicts) where conflicts are paths that already differ in canonical.
    """
    from app.services.storage import workspace_path

    root = workspace_path(project_id).resolve()
    team_dir = teammate_workspace_dir(project_id, run_id, teammate_id)
    dest_base = root / "swarm" / "".join(c for c in run_id if c.isalnum() or c in "-_")[:64] / canonical_subdir
    dest_base.mkdir(parents=True, exist_ok=True)
    promoted: list[str] = []
    conflicts: list[str] = []
    for rel in relative_paths:
        rel = rel.strip().lstrip("/").replace("..", "")
        if not rel:
            continue
        src = (team_dir / rel).resolve()
        dst = (dest_base / rel).resolve()
        try:
            src.relative_to(team_dir.resolve())
            dst.relative_to(dest_base.resolve())
        except ValueError:
            continue
        if not src.is_file():
            continue
        if dst.exists():
            if dst.read_bytes() != src.read_bytes():
                conflicts.append(rel)
                continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(src.read_bytes())
        promoted.append(rel)
    return promoted, conflicts
