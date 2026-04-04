"""Memory wiring, tools, and personalization (upgrade plan coverage)."""

from datetime import datetime

from app.core.config import settings
from app.db.models import MemoryItem, Project, User
from app.db.session import SessionLocal, init_db
from app.services.retrieval import TieredContextEngine
from app.services.tool_registry import memory_items


def test_assemble_v2_includes_user_preference_lines(tmp_path) -> None:
    old = settings.workspace_root
    settings.workspace_root = str(tmp_path)
    try:
        engine = TieredContextEngine()
        bundle = engine.assemble_v2(
            "p_mem",
            "Write an SOP",
            project_profile={
                "user_preference_lines": ["Use UK spelling", "C-suite audience"],
                "long_term_items": ["preference:tone=formal"],
            },
            char_cap=12000,
        )
        assert "UK spelling" in bundle.text
        assert "formal" in bundle.text
    finally:
        settings.workspace_root = old


def test_assemble_v2_includes_artifact_summary_events() -> None:
    engine = TieredContextEngine()
    events = [
        {"event_type": "artifact_summary", "payload": {"summary": "Generated narrative"}},
    ]
    bundle = engine.assemble_v2("px", "x", run_memory_events=events, char_cap=8000)
    assert "artifact_summary" in bundle.text
    assert "narrative" in bundle.text


def test_memory_items_tool_filters_denied_consent(monkeypatch) -> None:
    init_db()
    session = SessionLocal()
    old = settings.memory_respect_consent_in_context
    try:
        settings.memory_respect_consent_in_context = True
        session.add(User(id="um_u1", email="um_u1@example.com", hashed_password="x"))
        session.add(Project(id="um_p1", name="UM", created_by="um_u1"))
        session.add(
            MemoryItem(
                id="mem_denied",
                project_id="um_p1",
                memory_type="fact",
                key="k1",
                value="hidden",
                confidence="high",
                source="test",
                consent_state="denied",
                is_archived=False,
            )
        )
        session.add(
            MemoryItem(
                id="mem_ok",
                project_id="um_p1",
                memory_type="fact",
                key="k2",
                value="visible",
                confidence="high",
                source="test",
                consent_state="allowed",
                is_archived=False,
                updated_at=datetime.utcnow(),
            )
        )
        session.commit()
        out = memory_items(project_id="um_p1")
        assert out["count"] == 1
        assert out["items"][0]["key"] == "k2"
    finally:
        settings.memory_respect_consent_in_context = old
        session.close()


def test_memory_items_in_registry_schema() -> None:
    from app.services.tool_registry import TOOL_REGISTRY, tool_to_anthropic_schema

    assert "memory_items" in TOOL_REGISTRY
    schema = tool_to_anthropic_schema("memory_items")
    assert schema["name"] == "memory_items"




def test_merge_long_term_prefers_db_over_stale_profile() -> None:
    from app.services.memory_context import merge_long_term_items_into_profile

    profile: dict = {"long_term_items": ["stale:old=bad"]}

    class Row:
        memory_type = "fact"
        key = "k"
        value = "v"
        consent_state = "allowed"

    inj, skip, lskip = merge_long_term_items_into_profile(profile, [Row()], respect_consent=True)
    assert inj == 1 and skip == 0 and lskip == 0
    assert profile["long_term_items"] == ["fact:k=v"]


def test_merge_long_term_clears_stale_when_empty_or_all_denied() -> None:
    from app.services.memory_context import merge_long_term_items_into_profile

    profile: dict = {"long_term_items": ["stale:old=bad"]}
    inj, skip, lskip = merge_long_term_items_into_profile(profile, [], respect_consent=True)
    assert inj == 0 and skip == 0 and lskip == 0
    assert "long_term_items" not in profile

    profile2: dict = {"long_term_items": ["stale:old=bad"]}

    class Denied:
        memory_type = "fact"
        key = "k"
        value = "v"
        consent_state = "denied"

    inj2, skip2, ls2 = merge_long_term_items_into_profile(profile2, [Denied()], respect_consent=True)
    assert inj2 == 0 and skip2 == 1 and ls2 == 0
    assert "long_term_items" not in profile2


def test_merge_ledger_blocks_principal_without_grant() -> None:
    from app.services.memory_context import merge_long_term_items_into_profile

    init_db()
    session = SessionLocal()
    session.add(User(id="lc_u1", email="lc_u1@example.com", hashed_password="x"))
    session.add(Project(id="lc_p1", name="LC", created_by="lc_u1"))
    session.add(
        MemoryItem(
            id="mem_lc1",
            project_id="lc_p1",
            memory_type="fact",
            key="k",
            value="v",
            confidence="high",
            source="test",
            consent_state="allowed",
            principal_id="principal-a@example.com",
            is_archived=False,
            updated_at=datetime.utcnow(),
        )
    )
    session.commit()
    row = session.get(MemoryItem, "mem_lc1")
    profile: dict = {}
    inj, cs, ls = merge_long_term_items_into_profile(
        profile,
        [row],
        respect_consent=True,
        session=session,
        project_id="lc_p1",
        enforce_consent_ledger=True,
    )
    assert inj == 0 and cs == 0 and ls == 1
    session.close()


def test_merge_ledger_allows_when_grant_exists() -> None:
    from app.services.memory_context import merge_long_term_items_into_profile

    init_db()
    session = SessionLocal()
    session.add(User(id="lc_u2", email="lc_u2@example.com", hashed_password="x"))
    session.add(Project(id="lc_p2", name="LC2", created_by="lc_u2"))
    session.add(
        MemoryItem(
            id="mem_lc2",
            project_id="lc_p2",
            memory_type="fact",
            key="k",
            value="v2",
            confidence="high",
            source="test",
            consent_state="allowed",
            principal_id="principal-b@example.com",
            is_archived=False,
            updated_at=datetime.utcnow(),
        )
    )
    from app.db.models import ConsentLedger

    session.add(
        ConsentLedger(
            id="c_ledger_1",
            project_id="lc_p2",
            principal_id="principal-b@example.com",
            purpose="project_memory",
            granted=True,
        )
    )
    session.commit()
    row = session.get(MemoryItem, "mem_lc2")
    profile: dict = {}
    inj, cs, ls = merge_long_term_items_into_profile(
        profile,
        [row],
        respect_consent=True,
        session=session,
        project_id="lc_p2",
        enforce_consent_ledger=True,
    )
    assert inj == 1 and cs == 0 and ls == 0
    assert "fact:k=v2" in profile.get("long_term_items", [])[0]
    session.close()


def test_prometheus_text_includes_help_for_memory_counters() -> None:
    from app.services.observability import increment, prometheus_text

    increment("memory_items_injected_into_context_total", 2)
    text = prometheus_text()
    assert "# HELP memory_items_injected_into_context_total" in text
    assert "# TYPE memory_items_injected_into_context_total counter" in text
