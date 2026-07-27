from __future__ import annotations

from types import SimpleNamespace

from app.db.models import Project, Run, RunEvent, User
from app.db.session import SessionLocal, init_db
from app.services import run_worker
from app.services.run_event_service import RunEventService


def _publish_noop(_run_id: str, _event_id: int, _event_type: str, _payload: str) -> None:
    return


def test_execute_run_job_emits_resume_state_loaded(monkeypatch) -> None:
    init_db()
    session = SessionLocal()
    try:
        session.add(User(id="u_resflow", email="resflow@test.local", hashed_password="x"))
        session.add(Project(id="p_resflow", name="ResumeFlow", created_by="u_resflow"))
        session.add(
            Run(
                id="r_resflow",
                project_id="p_resflow",
                status="approved",
                output_types="[]",
                instruction="resume test",
                plan_payload="{}",
                approved_by="u_resflow",
                resume_requested=True,
            )
        )
        session.add(
            RunEvent(
                run_id="r_resflow",
                event_type="step",
                payload='{"event_type":"step","payload":{"status":"execution_enqueued"}}',
            )
        )
        session.commit()
    finally:
        session.close()

    monkeypatch.setattr(run_worker, "_run_event_service", RunEventService(publish_event=_publish_noop))
    monkeypatch.setattr(run_worker, "evaluate_permission_pipeline", lambda **_kwargs: [])
    monkeypatch.setattr(run_worker, "sync_disabled_hooks_from_db", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        run_worker,
        "run_hooks_sync",
        lambda *_args, **_kwargs: [SimpleNamespace(hook_name="stop_after_resume", outcome="ABORT", message="stop")],
    )

    ok, err = run_worker._execute_run_job("p_resflow", "r_resflow")
    assert ok is False
    assert isinstance(err, str)

    verify = SessionLocal()
    try:
        events = verify.query(RunEvent).filter_by(run_id="r_resflow").order_by(RunEvent.id.asc()).all()
        event_types = [e.event_type for e in events]
        assert "resume_state_loaded" in event_types
        assert "step" in event_types
    finally:
        verify.close()
