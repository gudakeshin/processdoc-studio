from __future__ import annotations

from app.db.models import Project, Run, User
from app.db.session import SessionLocal, init_db
from app.services.run_event_service import RunEventService


def _publish_noop(_run_id: str, _event_id: int, _event_type: str, _payload: str) -> None:
    return


def test_run_event_service_resume_state_and_enqueue_detection() -> None:
    init_db()
    session = SessionLocal()
    try:
        session.add(User(id="u_resev", email="resev@test.local", hashed_password="x"))
        session.add(Project(id="p_resev", name="ResEv", created_by="u_resev"))
        session.add(
            Run(
                id="r_resev",
                project_id="p_resev",
                status="approved",
                output_types="[]",
                instruction="run test",
                plan_payload="{}",
            )
        )
        session.commit()

        svc = RunEventService(publish_event=_publish_noop)
        svc.record_event(session, run_id="r_resev", event_type="step", payload_obj={"status": "execution_enqueued"})
        session.commit()
        assert svc.has_execution_enqueued_not_started(session, run_id="r_resev") is True
        state = svc.load_resume_state(session, run_id="r_resev")
        assert state["event_count"] >= 1
        assert state["last_step_status"] == "execution_enqueued"
    finally:
        session.close()
