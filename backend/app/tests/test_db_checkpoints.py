from __future__ import annotations

import pytest

from app.core.db_checkpoints import checkpoint_scope


class _DummySession:
    def __init__(self) -> None:
        self.rollback_calls = 0

    def rollback(self) -> None:
        self.rollback_calls += 1


def test_checkpoint_scope_marks_success() -> None:
    session = _DummySession()
    with checkpoint_scope(session, "unit.flow", metadata={"project_id": "p1"}) as cp:
        cp.mark("step_one", mode="test")
    snap = cp.snapshot()
    assert snap["name"] == "unit.flow"
    assert any(item.get("stage") == "scope_opened" for item in snap["checkpoints"])
    assert any(item.get("stage") == "scope_completed" for item in snap["checkpoints"])
    assert session.rollback_calls == 0


def test_checkpoint_scope_rolls_back_on_error() -> None:
    session = _DummySession()
    with pytest.raises(RuntimeError):
        with checkpoint_scope(session, "unit.failure") as cp:
            cp.mark("before_crash")
            raise RuntimeError("boom")
    assert session.rollback_calls == 1
