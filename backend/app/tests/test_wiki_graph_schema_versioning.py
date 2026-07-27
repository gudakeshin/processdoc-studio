import json

from app.core.config import settings
from app.services.wiki_graph import _build_and_persist_relationships, _load_persistent_graph


def test_build_relationships_writes_schema_envelope(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "workspace_root", str(tmp_path))
    monkeypatch.setattr(settings, "wiki_meta_schema_versioning_enabled", True)

    wiki_dir = tmp_path / "p1" / "wiki"
    wiki_dir.mkdir(parents=True, exist_ok=True)
    (wiki_dir / "a.md").write_text('---\ntitle: "A"\n---\n# A\n')
    (wiki_dir / "b.md").write_text('---\ntitle: "B"\n---\n# B\n[[a|A]]\n')

    _build_and_persist_relationships("project", "p1")

    rel_file = wiki_dir / ".meta" / "relationships.json"
    payload = json.loads(rel_file.read_text(encoding="utf-8"))
    assert payload["schema_version"] >= 1
    assert "data" in payload
    assert "relationships" in payload["data"]


def test_load_persistent_graph_reads_old_style_payload(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "workspace_root", str(tmp_path))
    monkeypatch.setattr(settings, "wiki_meta_schema_versioning_enabled", True)

    wiki_dir = tmp_path / "p2" / "wiki" / ".meta"
    wiki_dir.mkdir(parents=True, exist_ok=True)
    # Old-style shape (no schema_version envelope)
    (wiki_dir / "graph.json").write_text(
        json.dumps(
            {
                "graph": {"directed": False, "multigraph": False, "graph": {}, "nodes": [], "links": []},
                "page_titles": {},
                "metadata": {"last_updated": "2026-01-01T00:00:00Z"},
            }
        ),
        encoding="utf-8",
    )

    graph, page_titles, metadata = _load_persistent_graph("project", "p2")
    assert graph is not None
    assert page_titles == {}
    assert metadata.get("last_updated") == "2026-01-01T00:00:00Z"
