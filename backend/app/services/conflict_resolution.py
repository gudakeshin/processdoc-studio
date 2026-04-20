from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

HIGH_RISK_TYPES = {"type_mismatch", "formula_changed", "structural_shift"}


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _read_json(path: Path, fallback: Any) -> Any:
    if not path.exists():
        return fallback
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return fallback


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def conflicts_dir(excel_dir: Path) -> Path:
    root = excel_dir / "conflicts"
    root.mkdir(parents=True, exist_ok=True)
    return root


def audit_log_path(excel_dir: Path) -> Path:
    return conflicts_dir(excel_dir) / "audit_log.jsonl"


def classify_conflict(base: Any, local: Any, remote: Any) -> str:
    if isinstance(local, str) and local.startswith("=") and local != remote:
        return "formula_changed"
    if type(local) is not type(remote):
        return "type_mismatch"
    if base is None and remote is None and local is not None:
        return "deleted_range"
    if isinstance(local, str) and isinstance(remote, str) and (":" in local) != (":" in remote):
        return "structural_shift"
    if local != remote:
        return "value_mismatch"
    return "value_mismatch"


def create_conflict(
    excel_dir: Path,
    *,
    sheet: str,
    cell_ref: str,
    base_value: Any,
    local_value: Any,
    remote_value: Any,
    actor: str,
) -> dict[str, Any]:
    conflict_type = classify_conflict(base_value, local_value, remote_value)
    cid = f"cnf_{uuid4().hex[:10]}"
    payload = {
        "id": cid,
        "sheet": sheet,
        "cell_ref": cell_ref,
        "type": conflict_type,
        "severity": "high" if conflict_type in HIGH_RISK_TYPES else "medium",
        "status": "open",
        "base": {"value": base_value},
        "local": {"value": local_value},
        "remote": {"value": remote_value},
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
        "created_by": actor,
        "resolution": None,
    }
    _write_json(conflicts_dir(excel_dir) / f"{cid}.json", payload)
    append_audit_event(
        excel_dir,
        {
            "event": "conflict_detected",
            "conflict_id": cid,
            "actor": actor,
            "timestamp": _now_iso(),
            "type": conflict_type,
        },
    )
    return payload


def list_conflicts(excel_dir: Path) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for p in sorted(conflicts_dir(excel_dir).glob("cnf_*.json")):
        payload = _read_json(p, None)
        if isinstance(payload, dict):
            items.append(payload)
    return items


def get_conflict(excel_dir: Path, conflict_id: str) -> dict[str, Any] | None:
    payload = _read_json(conflicts_dir(excel_dir) / f"{conflict_id}.json", None)
    return payload if isinstance(payload, dict) else None


def append_audit_event(excel_dir: Path, event: dict[str, Any]) -> None:
    path = audit_log_path(excel_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(event) + "\n")


def resolve_conflict(
    excel_dir: Path,
    *,
    conflict_id: str,
    actor: str,
    chosen_side: str,
    rationale: str | None,
) -> dict[str, Any] | None:
    payload = get_conflict(excel_dir, conflict_id)
    if payload is None:
        return None
    payload["status"] = "resolved"
    payload["updated_at"] = _now_iso()
    payload["resolution"] = {
        "chosen_side": chosen_side,
        "rationale": rationale or "",
        "actor": actor,
        "timestamp": _now_iso(),
    }
    _write_json(conflicts_dir(excel_dir) / f"{conflict_id}.json", payload)
    append_audit_event(
        excel_dir,
        {
            "event": "conflict_resolved",
            "conflict_id": conflict_id,
            "actor": actor,
            "timestamp": _now_iso(),
            "chosen_side": chosen_side,
        },
    )
    return payload


def reopen_conflict(excel_dir: Path, *, conflict_id: str, actor: str, reason: str | None) -> dict[str, Any] | None:
    payload = get_conflict(excel_dir, conflict_id)
    if payload is None:
        return None
    payload["status"] = "open"
    payload["updated_at"] = _now_iso()
    payload["reopen"] = {"actor": actor, "reason": reason or "", "timestamp": _now_iso()}
    _write_json(conflicts_dir(excel_dir) / f"{conflict_id}.json", payload)
    append_audit_event(
        excel_dir,
        {
            "event": "conflict_reopened",
            "conflict_id": conflict_id,
            "actor": actor,
            "timestamp": _now_iso(),
            "reason": reason or "",
        },
    )
    return payload


def unresolved_high_risk_count(excel_dir: Path) -> int:
    count = 0
    for item in list_conflicts(excel_dir):
        if item.get("status") != "resolved" and item.get("type") in HIGH_RISK_TYPES:
            count += 1
    return count

