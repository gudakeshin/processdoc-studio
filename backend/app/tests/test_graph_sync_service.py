from pathlib import Path

from app.services.graph_sync import (
    load_checkpoint,
    queue_local_change,
    run_graph_sync_tick,
)


def test_graph_sync_idempotent_request_and_resume_state(tmp_path: Path) -> None:
    excel_dir = tmp_path / "excel"
    excel_dir.mkdir(parents=True, exist_ok=True)

    first = run_graph_sync_tick(
        excel_dir=excel_dir,
        mode="graph-local",
        actor="tester@example.com",
        request_id="req_fixed",
    )
    assert first["status"] == "synced"
    assert first.get("idempotent_replay") in {None, False}

    second = run_graph_sync_tick(
        excel_dir=excel_dir,
        mode="graph-local",
        actor="tester@example.com",
        request_id="req_fixed",
    )
    assert second["status"] == "synced"
    assert second.get("idempotent_replay") is True

    checkpoint = load_checkpoint(excel_dir)
    assert checkpoint["state"] == "idle"
    assert checkpoint.get("last_request_id") == "req_fixed"


def test_graph_sync_applies_queued_local_pushes(tmp_path: Path) -> None:
    excel_dir = tmp_path / "excel"
    excel_dir.mkdir(parents=True, exist_ok=True)
    queue_local_change(excel_dir=excel_dir, cell_ref="Sheet1!B2", value=123, actor="tester@example.com")
    queue_local_change(excel_dir=excel_dir, cell_ref="Sheet1!B3", value=456, actor="tester@example.com")

    result = run_graph_sync_tick(
        excel_dir=excel_dir,
        mode="graph-local",
        actor="tester@example.com",
        request_id="req_push_1",
    )
    assert result["status"] == "synced"
    assert result.get("pushed") == 2

