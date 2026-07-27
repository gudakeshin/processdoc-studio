"""Shared low-level file-resolution helpers for the wiki_*.py services.

Kept intentionally small: this centralizes only the file-path resolution logic
that was byte-identical across wiki_lint.py and wiki_graph.py. Read/write and
schema-normalization logic stays in each module since those have diverged
(see app.services.wiki_graph._normalize_relationships_payload) and merging
them further would change behavior without test coverage to verify it.
"""

from __future__ import annotations

from pathlib import Path


def resolve_relationships_file(wiki_dir: Path) -> Path | None:
    """Return the relationships.json path for a wiki dir, or None if absent.

    Checks the current `.meta/relationships.json` location first, then falls
    back to the legacy `relationships.json` at the wiki root.
    """
    relationships_file = wiki_dir / ".meta" / "relationships.json"
    if relationships_file.exists():
        return relationships_file
    relationships_file = wiki_dir / "relationships.json"
    if relationships_file.exists():
        return relationships_file
    return None
