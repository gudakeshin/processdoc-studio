from __future__ import annotations

from app.db.models import Project, ProjectMemoryProfile, User
from app.db.session import SessionLocal, init_db
from app.services.memory_event_service import (
    get_aggregated_profile,
    record_discovery_answer,
    record_routing_decision,
)


def test_memory_event_service_updates_project_profile_per_user() -> None:
    init_db()
    session = SessionLocal()
    try:
        session.add(User(id="u_memsvc", email="memsvc@test.local", hashed_password="x"))
        session.add(Project(id="p_memsvc", name="MemSvc", created_by="u_memsvc"))
        session.commit()

        record_discovery_answer(
            session,
            project_id="p_memsvc",
            user_id="u_memsvc",
            slot_key="audience",
            value="healthcare execs",
        )
        record_routing_decision(
            session,
            project_id="p_memsvc",
            user_id="u_memsvc",
            decision_type="discovery_answer",
            confidence=0.9,
            outcome="captured_required_slots",
        )
        session.commit()

        profile = get_aggregated_profile(session, project_id="p_memsvc", user_id="u_memsvc")
        assert profile["aggregated_slots"]["audience"] == "healthcare execs"
        assert profile["decision_outcomes"]["discovery_answer"]["count"] == 1
        row = session.query(ProjectMemoryProfile).filter_by(project_id="p_memsvc").one()
        assert row.summary_json
    finally:
        session.close()
