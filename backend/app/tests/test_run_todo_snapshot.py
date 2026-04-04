from app.services.run_todo_snapshot import (
    build_run_todo_rows,
    emit_run_todo_snapshot,
    todo_set_status,
)


def test_build_run_todo_rows_order_and_labels() -> None:
    rows = build_run_todo_rows(["pptx", "narrative"], milestone_labels={"out:pptx": "Executive storyline"})
    ids = [r["id"] for r in rows]
    assert ids[:3] == ["context", "process_model", "plan"]
    assert "out:pptx" in ids
    assert "out:narrative" in ids
    pptx_row = next(r for r in rows if r["id"] == "out:pptx")
    assert pptx_row["label"] == "Executive storyline"
    assert all(r["status"] == "pending" for r in rows)


def test_emit_run_todo_snapshot_calls_emit() -> None:
    seen: list[tuple[str, dict]] = []

    def emit(et: str, pl: dict) -> None:
        seen.append((et, pl))

    rows = build_run_todo_rows(["pdf"])
    todo_set_status(rows, "context", "done")
    emit_run_todo_snapshot(emit, rows)
    assert len(seen) == 1
    assert seen[0][0] == "run_todo_snapshot"
    assert len(seen[0][1]["todos"]) == len(rows)
