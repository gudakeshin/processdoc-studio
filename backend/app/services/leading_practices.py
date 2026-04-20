from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.services.cache import cache_service


class LeadingPracticeLibraryService:
    """
    Leading Practice Library (LP) retrieval service.

    This phase implements a local-index mode (via `LP_LIBRARY_LOCAL_PATH`)
    and provides the same interface required for later OneDrive/Graph integration.
    If local indexing/Graph credentials are not available, `search` returns [] safely.
    """

    def __init__(self) -> None:
        self._index_loaded = False
        self._index: list[dict[str, Any]] = []

    def _index_path(self) -> Path:
        return Path(settings.workspace_root) / ".lp_index" / "index.json"

    def _load_index(self) -> None:
        index_file = self._index_path()
        if not index_file.exists():
            self._index = []
            self._index_loaded = True
            return
        try:
            data = json.loads(index_file.read_text(encoding="utf-8"))
            idx = data.get("items") if isinstance(data, dict) else None
            self._index = idx if isinstance(idx, list) else []
        except Exception:
            self._index = []
        self._index_loaded = True

    def ensure_index(self, *, force: bool = False) -> None:
        if self._index_loaded and not force:
            return

        # Local indexing (developer mode).
        local_root = settings.lp_library_local_path
        refresh_s = 6 * 60 * 60
        index_file = self._index_path()

        if not force and index_file.exists():
            age_s = time.time() - index_file.stat().st_mtime
            if age_s < refresh_s:
                self._load_index()
                return

        items: list[dict[str, Any]] = []
        if local_root:
            root = Path(local_root)
            if root.exists():
                for p in root.rglob("*"):
                    if not p.is_file():
                        continue
                    if p.suffix.lower() not in {".md", ".txt"}:
                        continue
                    try:
                        text = p.read_text(encoding="utf-8", errors="ignore").strip()
                    except Exception:  # noqa: S112 — best-effort, non-fatal
                        continue
                    if not text:
                        continue

                    # Very simple section chunking: split on lines starting with '# '.
                    sections = text.split("\n# ")
                    for sec_i, sec in enumerate(sections):
                        sec_text = sec.strip()
                        if not sec_text:
                            continue
                        heading = ""
                        if sec_i > 0:
                            # For sections after the first split, the heading is before the next newline.
                            heading = sec_text.splitlines()[0][:120]
                        snippet = sec_text[:2000]
                        items.append(
                            {
                                "id": hashlib.sha256(str(p) + str(sec_i)).hexdigest()[:16],
                                "path": str(p),
                                "heading": heading,
                                "text": snippet,
                            }
                        )

        # Persist index (so subsequent searches are fast).
        index_file.parent.mkdir(parents=True, exist_ok=True)
        index_file.write_text(json.dumps({"items": items}, indent=2), encoding="utf-8")
        self._index_loaded = False
        self._load_index()

    def search(
        self,
        query: str,
        *,
        project_id: str | None = None,
        dpdp_enabled: bool = False,  # placeholder for later DPDP tagging exclusions
        max_results: int = 5,
    ) -> list[dict[str, Any]]:
        q = (query or "").strip()
        if not q:
            return []

        cache_key = f"lpsearch:{project_id or 'global'}:{hashlib.sha256(q.encode('utf-8')).hexdigest()[:16]}"
        cached = cache_service.get(cache_key)
        if cached and isinstance(cached, dict) and isinstance(cached.get("results"), list):
            return cached["results"]

        try:
            self.ensure_index(force=False)
            if not self._index:
                return []

            # Deterministic relevance: tokenize query terms and compute overlap.
            q_terms = {t for t in q.lower().split() if len(t) > 2}
            scored: list[tuple[float, dict[str, Any]]] = []
            for it in self._index:
                text = (it.get("text") or "").lower()
                if not text:
                    continue
                t_terms = set(text.split())
                overlap = len(q_terms & t_terms)
                if overlap <= 0:
                    continue
                # Relevance score: overlap normalized by query size.
                score = overlap / max(1, len(q_terms))
                scored.append((score, it))

            scored.sort(key=lambda x: x[0], reverse=True)
            results = []
            for score, it in scored[:max_results]:
                results.append(
                    {
                        "id": it.get("id"),
                        "path": it.get("path"),
                        "heading": it.get("heading") or "",
                        "text": it.get("text") or "",
                        "relevance_score": float(score),
                    }
                )
        except Exception:
            results = []

        cache_service.set(cache_key, {"results": results}, ttl_seconds=300)
        return results


leading_practice_library_service = LeadingPracticeLibraryService()

