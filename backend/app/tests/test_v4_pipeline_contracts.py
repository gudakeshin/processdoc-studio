import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.core.config import settings
from app.db.models import MemoryEvent, Project, ProjectMemoryProfile, Run, User
from app.db.session import SessionLocal, init_db
from app.services.dpdp import DPDPService
from app.services.retrieval import TieredContextEngine
from app.services.run_worker import append_memory_event, upsert_project_memory_profile
from app.services.storage import save_run_artifacts
from app.services.web_search import WebSearchService


def test_storage_uses_spec_filenames(tmp_path) -> None:
    old_root = settings.workspace_root
    settings.workspace_root = str(tmp_path)
    try:
        payload = {
            "drawio_xml": "<mxGraphModel/>",
            "raci_html": "<table></table>",
            "sop_markdown": "# SOP",
            "narrative_md": "# Narrative",
            "assembled_context": "context",
            "dpdp_report_json": {"gate7_pass": True},
            "qa_report": {"passed": True},
            "guardrail_report": {"status": "pass"},
        }
        save_run_artifacts("p1", "r1", payload)
        run_dir = Path(tmp_path) / "p1" / "runs" / "r1"
        assert (run_dir / "drawio.xml").exists()
        assert (run_dir / "raci.html").exists()
        assert (run_dir / "sop.md").exists()
        assert (run_dir / "narrative.md").exists()
        assert (run_dir / "qa_report.json").exists()
        assert (run_dir / "guardrail_report.json").exists()
        assert (run_dir / "dpdp_report.json").exists()
    finally:
        settings.workspace_root = old_root


def test_retrieval_assembles_from_parsed_docs(tmp_path) -> None:
    old_root = settings.workspace_root
    settings.workspace_root = str(tmp_path)
    try:
        project_dir = Path(tmp_path) / "p1"
        (project_dir / "parsed_docs").mkdir(parents=True, exist_ok=True)
        (project_dir / "CONTEXT.md").write_text("Project context", encoding="utf-8")
        (project_dir / "parsed_docs" / "doc1.json").write_text(
            json.dumps({"chunks": ["Vendor onboarding process has approval step.", "Unrelated finance note."]}),
            encoding="utf-8",
        )
        engine = TieredContextEngine()
        bundle = engine.assemble("p1", "vendor onboarding approval", lp_snippets=["LP sample"])
        assert "Project context" in bundle.text
        assert "LP sample" in bundle.text
        assert "Vendor onboarding process" in bundle.text
    finally:
        settings.workspace_root = old_root


def test_dpdp_gate7_fails_when_pii_present() -> None:
    service = DPDPService()
    _, report = service.redact("PAN ABCDE1234F and Aadhaar 1234 5678 9012")
    assert report["pii_entities_redacted"] >= 2
    assert report["gate7_pass"] is False


def test_web_search_safe_without_api_keys() -> None:
    svc = WebSearchService()
    results = svc.search("consulting benchmarks", project_id="p1")
    assert isinstance(results, list)


def test_memory_event_write_read_sequence() -> None:
    init_db()
    session = SessionLocal()
    try:
        session.add(User(id="u1", email="u1@example.com", hashed_password="x"))
        session.add(Project(id="p1", name="P1", created_by="u1"))
        session.add(
            Run(
                id="r1",
                project_id="p1",
                status="plan_ready",
                output_types="[]",
                instruction="test",
                plan_payload="{}",
            )
        )
        session.commit()
        append_memory_event(
            session,
            project_id="p1",
            run_id="r1",
            event_type="user_intent_updated",
            payload_obj={"summary": "first"},
        )
        append_memory_event(
            session,
            project_id="p1",
            run_id="r1",
            event_type="qa_outcome",
            payload_obj={"summary": "second"},
        )
        session.commit()
        rows = session.query(MemoryEvent).filter_by(project_id="p1", run_id="r1").order_by(MemoryEvent.id.asc()).all()
        assert len(rows) == 2
        assert rows[0].event_type == "user_intent_updated"
        assert rows[1].event_type == "qa_outcome"
    finally:
        session.close()


def test_memory_event_dedup_by_fingerprint() -> None:
    init_db()
    session = SessionLocal()
    try:
        session.add(User(id="u3", email="u3@example.com", hashed_password="x"))
        session.add(Project(id="p3", name="P3", created_by="u3"))
        session.add(
            Run(
                id="r3",
                project_id="p3",
                status="plan_ready",
                output_types="[]",
                instruction="test",
                plan_payload="{}",
            )
        )
        session.commit()

        append_memory_event(
            session,
            project_id="p3",
            run_id="r3",
            event_type="qa_outcome",
            payload_obj={"summary": "pass", "scores": {"x": 0.9}},
        )
        append_memory_event(
            session,
            project_id="p3",
            run_id="r3",
            event_type="qa_outcome",
            payload_obj={"scores": {"x": 0.9}, "summary": "pass"},
        )
        session.commit()
        rows = session.query(MemoryEvent).filter_by(project_id="p3", run_id="r3").all()
        assert len(rows) == 1
    finally:
        session.close()


def test_assemble_v2_budget_and_deterministic_trim(tmp_path) -> None:
    old_root = settings.workspace_root
    settings.workspace_root = str(tmp_path)
    try:
        project_dir = Path(tmp_path) / "p1"
        (project_dir / "parsed_docs").mkdir(parents=True, exist_ok=True)
        (project_dir / "CONTEXT.md").write_text("Context baseline " * 100, encoding="utf-8")
        (project_dir / "parsed_docs" / "doc1.json").write_text(
            json.dumps({"chunks": ["A " * 800, "B " * 800, "C " * 800]}),
            encoding="utf-8",
        )
        engine = TieredContextEngine()
        events = [{"event_type": "qa_remediation", "payload": {"summary": "Fix checklist item"}}]
        profile = {"non_negotiables": ["Must include approval matrix", "No PII in output"]}
        first = engine.assemble_v2("p1", "Build onboarding SOP", run_memory_events=events, project_profile=profile, char_cap=2400)
        second = engine.assemble_v2("p1", "Build onboarding SOP", run_memory_events=events, project_profile=profile, char_cap=2400)
        assert len(first.text) <= 2400
        assert first.text == second.text
        assert isinstance(first.metadata, dict)
        assert "dropped_items" in first.metadata
    finally:
        settings.workspace_root = old_root


def test_project_memory_profile_carryover_upsert() -> None:
    init_db()
    session = SessionLocal()
    try:
        session.add(User(id="u2", email="u2@example.com", hashed_password="x"))
        session.add(Project(id="p2", name="P2", created_by="u2"))
        session.commit()
        upsert_project_memory_profile(
            session,
            "p2",
            {"non_negotiables": ["Use approved template"], "recent_changes": ["qa fix"]},
        )
        session.commit()
        upsert_project_memory_profile(
            session,
            "p2",
            {
                "non_negotiables": ["Use approved template", "use approved template ", "No PII"],
                "recent_changes": ["guardrail pass", "Guardrail pass"],
            },
        )
        session.commit()
        row = session.query(ProjectMemoryProfile).filter_by(project_id="p2").one()
        payload = json.loads(row.summary_json)
        assert payload["non_negotiables"] == ["Use approved template", "No PII"]
        assert payload["recent_changes"] == ["guardrail pass"]
    finally:
        session.close()


def test_memory_event_retention_days_setting() -> None:
    init_db()
    session = SessionLocal()
    old_retention = settings.memory_events_retention_days
    try:
        session.add(User(id="u4", email="u4@example.com", hashed_password="x"))
        session.add(Project(id="p4", name="P4", created_by="u4"))
        session.add(
            Run(
                id="r4",
                project_id="p4",
                status="plan_ready",
                output_types="[]",
                instruction="test",
                plan_payload="{}",
            )
        )
        session.commit()
        session.add(
            MemoryEvent(
                project_id="p4",
                run_id="r4",
                event_type="qa_outcome",
                fingerprint="legacy_old",
                payload=json.dumps({"summary": "old"}),
                created_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(days=45),
            )
        )
        session.commit()

        settings.memory_events_retention_days = 30
        append_memory_event(
            session,
            project_id="p4",
            run_id="r4",
            event_type="qa_outcome",
            payload_obj={"summary": "new"},
        )
        session.commit()
        rows = session.query(MemoryEvent).filter_by(project_id="p4", run_id="r4").all()
        assert len(rows) == 1

        session.add(
            MemoryEvent(
                project_id="p4",
                run_id="r4",
                event_type="qa_outcome",
                fingerprint="legacy_old_2",
                payload=json.dumps({"summary": "old-keep"}),
                created_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(days=45),
            )
        )
        session.commit()
        settings.memory_events_retention_days = 0
        append_memory_event(
            session,
            project_id="p4",
            run_id="r4",
            event_type="guardrail_outcome",
            payload_obj={"summary": "pass"},
        )
        session.commit()
        rows_after_disabled = session.query(MemoryEvent).filter_by(project_id="p4", run_id="r4").all()
        assert len(rows_after_disabled) == 3
    finally:
        settings.memory_events_retention_days = old_retention
        session.close()


def test_project_level_retention_days_override(tmp_path) -> None:
    old_root = settings.workspace_root
    old_retention = settings.memory_events_retention_days
    settings.workspace_root = str(tmp_path)
    settings.memory_events_retention_days = 30
    init_db()
    session = SessionLocal()
    try:
        project_dir = Path(tmp_path) / "p5"
        project_dir.mkdir(parents=True, exist_ok=True)
        (project_dir / "settings.json").write_text(
            json.dumps({"memory_events_retention_days": 0}),
            encoding="utf-8",
        )
        session.add(User(id="u5", email="u5@example.com", hashed_password="x"))
        session.add(Project(id="p5", name="P5", created_by="u5"))
        session.add(
            Run(
                id="r5",
                project_id="p5",
                status="plan_ready",
                output_types="[]",
                instruction="test",
                plan_payload="{}",
            )
        )
        session.commit()
        session.add(
            MemoryEvent(
                project_id="p5",
                run_id="r5",
                event_type="qa_outcome",
                fingerprint="legacy_keep",
                payload=json.dumps({"summary": "old"}),
                created_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(days=60),
            )
        )
        session.commit()
        append_memory_event(
            session,
            project_id="p5",
            run_id="r5",
            event_type="guardrail_outcome",
            payload_obj={"summary": "pass"},
        )
        session.commit()
        rows = session.query(MemoryEvent).filter_by(project_id="p5", run_id="r5").all()
        assert len(rows) == 2
    finally:
        settings.workspace_root = old_root
        settings.memory_events_retention_days = old_retention
        session.close()
