from __future__ import annotations

from datetime import datetime
from app.core.tz import IST
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx

_GRAPH_HTTP_CLIENT = httpx.Client(timeout=3.0)


def _now_iso() -> str:
    return datetime.now(IST).isoformat()


def _read_json(path: Path, fallback: Any) -> Any:
    if not path.exists():
        return fallback
    try:
        import json

        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return fallback


def _write_json(path: Path, payload: Any) -> None:
    import json

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def sync_root(excel_dir: Path) -> Path:
    root = excel_dir / "sync"
    root.mkdir(parents=True, exist_ok=True)
    return root


def checkpoint_path(excel_dir: Path) -> Path:
    return sync_root(excel_dir) / "checkpoint.json"


def cell_ref_map_path(excel_dir: Path) -> Path:
    return sync_root(excel_dir) / "cell_ref_map.json"


def dead_letter_path(excel_dir: Path) -> Path:
    return sync_root(excel_dir) / "dead_letter.json"


def request_log_path(excel_dir: Path) -> Path:
    return sync_root(excel_dir) / "request_ids.json"


def remote_shadow_path(excel_dir: Path) -> Path:
    return sync_root(excel_dir) / "remote_shadow.json"


def local_pending_push_path(excel_dir: Path) -> Path:
    return sync_root(excel_dir) / "local_pending_push.json"


def load_checkpoint(excel_dir: Path) -> dict[str, Any]:
    return _read_json(
        checkpoint_path(excel_dir),
        {
            "state": "idle",
            "delta_token": None,
            "last_remote_revision": None,
            "last_applied_change_id": None,
            "last_pull_at": None,
            "last_push_at": None,
            "last_error": None,
            "updated_at": _now_iso(),
        },
    )


def save_checkpoint(excel_dir: Path, payload: dict[str, Any]) -> dict[str, Any]:
    payload["updated_at"] = _now_iso()
    _write_json(checkpoint_path(excel_dir), payload)
    return payload


def ensure_cell_ref_map(excel_dir: Path) -> dict[str, Any]:
    path = cell_ref_map_path(excel_dir)
    payload = _read_json(path, None)
    if isinstance(payload, dict):
        return payload
    payload = {"version": 1, "mappings": {}, "updated_at": _now_iso()}
    _write_json(path, payload)
    return payload


def load_dead_letter(excel_dir: Path) -> list[dict[str, Any]]:
    payload = _read_json(dead_letter_path(excel_dir), [])
    return payload if isinstance(payload, list) else []


def load_request_log(excel_dir: Path) -> dict[str, Any]:
    payload = _read_json(request_log_path(excel_dir), {"seen_request_ids": []})
    if not isinstance(payload, dict):
        payload = {"seen_request_ids": []}
    if not isinstance(payload.get("seen_request_ids"), list):
        payload["seen_request_ids"] = []
    return payload


def mark_request_seen(excel_dir: Path, request_id: str) -> bool:
    payload = load_request_log(excel_dir)
    seen = payload["seen_request_ids"]
    if request_id in seen:
        return False
    seen.append(request_id)
    payload["updated_at"] = _now_iso()
    _write_json(request_log_path(excel_dir), payload)
    return True


def _graph_http_probe() -> bool:
    base_url = (
        __import__("os").getenv("GRAPH_API_BASE_URL", "").strip()
        or "https://graph.microsoft.com/v1.0"
    )
    token = __import__("os").getenv("GRAPH_ACCESS_TOKEN", "").strip()
    if not token:
        return False
    try:
        resp = _GRAPH_HTTP_CLIENT.get(
            f"{base_url}/me/drive",
            headers={"Authorization": f"Bearer {token}"},
        )
        return resp.status_code < 400
    except Exception:
        return False


def _load_remote_shadow(excel_dir: Path) -> dict[str, Any]:
    payload = _read_json(
        remote_shadow_path(excel_dir),
        {"revision": "rev_seed", "delta_token": "delta_seed", "changes": []},
    )
    return payload if isinstance(payload, dict) else {"revision": "rev_seed", "delta_token": "delta_seed", "changes": []}


def _load_local_pending(excel_dir: Path) -> list[dict[str, Any]]:
    payload = _read_json(local_pending_push_path(excel_dir), [])
    return payload if isinstance(payload, list) else []


def _save_local_pending(excel_dir: Path, payload: list[dict[str, Any]]) -> None:
    _write_json(local_pending_push_path(excel_dir), payload)


def _apply_remote_changes(excel_dir: Path, changes: list[dict[str, Any]]) -> int:
    # Normalized local projection for now; later this maps into model assumptions.
    projection_path = sync_root(excel_dir) / "local_projection.json"
    projection = _read_json(projection_path, {"cells": {}, "updated_at": _now_iso()})
    if not isinstance(projection, dict):
        projection = {"cells": {}, "updated_at": _now_iso()}
    if not isinstance(projection.get("cells"), dict):
        projection["cells"] = {}
    applied = 0
    for change in changes:
        cell = str(change.get("cell_ref") or "")
        if not cell:
            continue
        projection["cells"][cell] = {
            "value": change.get("value"),
            "source": "remote",
            "applied_at": _now_iso(),
        }
        applied += 1
    projection["updated_at"] = _now_iso()
    _write_json(projection_path, projection)
    return applied


def queue_local_change(excel_dir: Path, cell_ref: str, value: Any, actor: str) -> dict[str, Any]:
    pending = _load_local_pending(excel_dir)
    item = {
        "id": f"push_{uuid4().hex[:8]}",
        "cell_ref": cell_ref,
        "value": value,
        "actor": actor,
        "created_at": _now_iso(),
    }
    pending.append(item)
    _save_local_pending(excel_dir, pending)
    return item


def append_dead_letter(excel_dir: Path, item: dict[str, Any]) -> dict[str, Any]:
    queue = load_dead_letter(excel_dir)
    record = {
        "id": item.get("id") or f"dlq_{uuid4().hex[:10]}",
        "created_at": _now_iso(),
        "status": "queued",
        **item,
    }
    queue.append(record)
    _write_json(dead_letter_path(excel_dir), queue)
    return record


def replay_dead_letter_item(excel_dir: Path, item_id: str) -> dict[str, Any] | None:
    queue = load_dead_letter(excel_dir)
    found = None
    for item in queue:
        if item.get("id") == item_id:
            item["status"] = "replayed"
            item["replayed_at"] = _now_iso()
            found = item
            break
    if found is not None:
        _write_json(dead_letter_path(excel_dir), queue)
    return found


def simulate_sync_tick(excel_dir: Path, mode: str, actor: str) -> dict[str, Any]:
    checkpoint = load_checkpoint(excel_dir)
    ensure_cell_ref_map(excel_dir)

    request_id = f"req_{uuid4().hex[:10]}"
    checkpoint.update(
        {
            "state": "syncing",
            "mode": mode,
            "last_request_id": request_id,
            "last_pull_at": _now_iso(),
            "last_push_at": _now_iso(),
            "last_error": None,
        }
    )
    save_checkpoint(excel_dir, checkpoint)

    if mode == "force-fail":
        dlq_item = append_dead_letter(
            excel_dir,
            {
                "reason": "simulated_remote_failure",
                "request_id": request_id,
                "actor": actor,
                "retriable": True,
            },
        )
        checkpoint["state"] = "degraded"
        checkpoint["last_error"] = "simulated_remote_failure"
        save_checkpoint(excel_dir, checkpoint)
        return {
            "status": "degraded",
            "request_id": request_id,
            "dead_letter_item_id": dlq_item["id"],
            "checkpoint": checkpoint,
        }

    checkpoint["state"] = "idle"
    checkpoint["last_applied_change_id"] = f"chg_{uuid4().hex[:8]}"
    checkpoint["last_remote_revision"] = f"rev_{uuid4().hex[:8]}"
    checkpoint["delta_token"] = f"delta_{uuid4().hex[:8]}"
    save_checkpoint(excel_dir, checkpoint)
    return {"status": "synced", "request_id": request_id, "checkpoint": checkpoint}


def run_graph_sync_tick(excel_dir: Path, mode: str, actor: str, request_id: str) -> dict[str, Any]:
    checkpoint = load_checkpoint(excel_dir)
    ensure_cell_ref_map(excel_dir)

    # Idempotency guard: duplicated request_id should not mutate state again.
    if not mark_request_seen(excel_dir, request_id):
        return {"status": "synced", "request_id": request_id, "checkpoint": checkpoint, "idempotent_replay": True}

    checkpoint.update(
        {
            "state": "syncing",
            "mode": mode,
            "last_request_id": request_id,
            "last_error": None,
            "last_pull_at": _now_iso(),
        }
    )
    save_checkpoint(excel_dir, checkpoint)

    graph_connected = _graph_http_probe() if mode == "graph-api" else False
    remote = _load_remote_shadow(excel_dir)
    changes = remote.get("changes", [])
    if not isinstance(changes, list):
        changes = []

    applied = _apply_remote_changes(excel_dir, changes)

    pending_push = _load_local_pending(excel_dir)
    pushed = len(pending_push)
    _save_local_pending(excel_dir, [])

    if mode == "force-fail":
        item = append_dead_letter(
            excel_dir,
            {
                "reason": "graph_sync_push_failed",
                "request_id": request_id,
                "actor": actor,
                "retriable": True,
                "retry_count": 1,
                "backoff_seconds": 2,
            },
        )
        checkpoint["state"] = "degraded"
        checkpoint["last_error"] = "graph_sync_push_failed"
        save_checkpoint(excel_dir, checkpoint)
        return {
            "status": "degraded",
            "request_id": request_id,
            "dead_letter_item_id": item["id"],
            "checkpoint": checkpoint,
            "pull_applied": applied,
            "pushed": 0,
            "graph_connected": graph_connected,
        }

    checkpoint["state"] = "idle"
    checkpoint["last_applied_change_id"] = f"chg_{uuid4().hex[:8]}"
    checkpoint["last_remote_revision"] = str(remote.get("revision") or f"rev_{uuid4().hex[:8]}")
    checkpoint["delta_token"] = str(remote.get("delta_token") or f"delta_{uuid4().hex[:8]}")
    checkpoint["last_push_at"] = _now_iso()
    save_checkpoint(excel_dir, checkpoint)
    return {
        "status": "synced",
        "request_id": request_id,
        "checkpoint": checkpoint,
        "pull_applied": applied,
        "pushed": pushed,
        "graph_connected": graph_connected,
    }

