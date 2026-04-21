from __future__ import annotations

import json

from app.core.config import settings
from app.services.wiki_graph import _build_and_persist_relationships


def _write_page(path, title: str, body: str) -> None:
    path.write_text(
        f"""---
title: "{title}"
category: "document"
confidence: "medium"
last_updated: "2026-01-01T00:00:00+00:00"
created_at: "2026-01-01T00:00:00+00:00"
---

# {title}

{body}
""",
        encoding="utf-8",
    )


def test_relationships_generated_from_three_ingested_docs(tmp_path, monkeypatch):
    project_id = "proj_rel_test"
    workspace_root = tmp_path / "workspace"
    wiki_dir = workspace_root / project_id / "wiki"
    wiki_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(settings, "workspace_root", str(workspace_root))

    _write_page(
        wiki_dir / "doc_one.md",
        "Doc One",
        "Varroc P2P baseline references [[doc_two|Doc Two]] and SAP enablement.",
    )
    _write_page(
        wiki_dir / "doc_two.md",
        "Doc Two",
        "Doc Two links [[doc_three|Doc Three]] and expands P2P controls for Varroc.",
    )
    _write_page(
        wiki_dir / "doc_three.md",
        "Doc Three",
        "Doc Three mentions [[doc_one|Doc One]] and SAP workflow dependencies.",
    )

    result = _build_and_persist_relationships("project", project_id)
    assert result["total_relationships"] > 0

    rel_file = wiki_dir / ".meta" / "relationships.json"
    raw = json.loads(rel_file.read_text(encoding="utf-8"))
    # Support both legacy flat shape and schema-versioned envelope {schema_version, data}.
    payload = raw.get("data") if isinstance(raw.get("data"), dict) and "schema_version" in raw else raw
    rels = payload.get("relationships", [])
    assert len(rels) > 0

    inbound_outbound: dict[str, dict[str, int]] = {}
    for rel in rels:
        source = rel["source_id"]
        target = rel["target_id"]
        inbound_outbound.setdefault(source, {"inbound": 0, "outbound": 0})
        inbound_outbound.setdefault(target, {"inbound": 0, "outbound": 0})
        inbound_outbound[source]["outbound"] += 1
        inbound_outbound[target]["inbound"] += 1

    assert inbound_outbound["doc_one"]["outbound"] >= 1
    assert inbound_outbound["doc_two"]["inbound"] >= 1
    assert inbound_outbound["doc_three"]["inbound"] >= 1
