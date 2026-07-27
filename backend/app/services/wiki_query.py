"""
wiki_query.py — Wiki query helpers.

Handles wiki index loading, BM25 + embedding-rerank search, answer synthesis,
citation parsing, and answer quality evaluation.
"""
import json
import logging
import re
from pathlib import Path

_LOG = logging.getLogger(__name__)
_embed_model = None
_faiss_index = None
_index_metadata = None


# ---------------------------------------------------------------------------
# Index loading
# ---------------------------------------------------------------------------

def _get_wiki_index(wiki_type: str, project_id: str | None) -> dict | None:
    """Read all wiki pages and return an in-memory index."""
    try:
        from app.services.storage import workspace_path

        if wiki_type == "leading_practice":
            wiki_dir = workspace_path("leading_practices") / "wiki"
        else:
            wiki_dir = workspace_path(project_id) / "wiki"

        if not wiki_dir.exists():
            return {"pages": []}

        pages = []
        for md_file in wiki_dir.glob("*.md"):
            if md_file.name in ("index.md", "log.md"):
                continue
            try:
                content = md_file.read_text(encoding="utf-8")
                title = md_file.stem
                category = "artifact"

                fm_match = re.match(r"^---\n(.*?)\n---", content, re.DOTALL)
                if fm_match:
                    for line in fm_match.group(1).split("\n"):
                        if ":" in line:
                            k, v = line.split(":", 1)
                            k, v = k.strip(), v.strip().strip('"')
                            if k == "title":
                                title = v
                            elif k == "category":
                                category = v

                body = re.sub(r"^---\n.*?\n---\n?", "", content, flags=re.DOTALL).strip()
                pages.append({
                    "page_id": md_file.stem,
                    "title": title,
                    "category": category,
                    "content": body,
                })
            except Exception:  # noqa: S112 — best-effort, non-fatal
                continue

        return {"pages": pages}
    except Exception as e:
        _LOG.error(f"Error building wiki index: {e}")
        return {"pages": []}


# ---------------------------------------------------------------------------
# Embedding persistence — semantic search via FAISS index
# ---------------------------------------------------------------------------

def _compute_and_save_embeddings(pages: list, wiki_type: str, project_id: str | None) -> dict:
    """Compute embeddings for wiki pages and persist to FAISS index.

    Args:
        pages: List of page dicts with page_id, title, content
        wiki_type: "project" or "leading_practice"
        project_id: Project ID (None for leading_practice)

    Returns:
        {"computed": int, "saved": bool, "index_size": int}
    """
    if not pages:
        return {"computed": 0, "saved": False, "index_size": 0}

    try:
        from sentence_transformers import SentenceTransformer
        from app.services.storage import workspace_path
        import numpy as np

        global _embed_model
        if _embed_model is None:
            _embed_model = SentenceTransformer("all-MiniLM-L6-v2")

        # Get meta directory
        if wiki_type == "leading_practice":
            meta_dir = workspace_path("leading_practices") / "wiki" / ".meta"
        else:
            meta_dir = workspace_path(project_id) / "wiki" / ".meta"
        meta_dir.mkdir(parents=True, exist_ok=True)

        # Compute embeddings for all pages
        texts = [
            (p.get("title", "") + " " + p.get("content", "")[:800])
            for p in pages
        ]
        page_ids = [p.get("page_id") or p.get("title", "").lower().replace(" ", "_") for p in pages]

        embeddings = _embed_model.encode(texts, convert_to_tensor=False).astype(np.float32)

        # Save to FAISS
        try:
            import faiss
            index = faiss.IndexFlatL2(embeddings.shape[1])
            index.add(embeddings)
            faiss.write_index(index, str(meta_dir / "embeddings.faiss"))

            # Save metadata (page_ids and page info for reconstruction)
            metadata = {
                "page_ids": page_ids,
                "model": "all-MiniLM-L6-v2",
                "embedding_dim": int(embeddings.shape[1]),
                "count": len(page_ids),
            }
            (meta_dir / "embeddings_metadata.json").write_text(
                json.dumps(metadata, indent=2), encoding="utf-8"
            )

            _LOG.info(f"Saved embeddings for {len(page_ids)} pages to FAISS index")
            return {"computed": len(page_ids), "saved": True, "index_size": len(page_ids)}

        except ImportError:
            _LOG.warning("FAISS not installed; embeddings computed but not persisted")
            return {"computed": len(page_ids), "saved": False, "index_size": 0}

    except Exception as e:
        _LOG.warning(f"Embedding persistence failed: {e}")
        return {"computed": 0, "saved": False, "index_size": 0}


def _load_embeddings_index(wiki_type: str, project_id: str | None) -> tuple[object, dict] | None:
    """Load FAISS index and metadata from disk.

    Returns:
        (faiss_index, metadata_dict) or None if not available
    """
    global _faiss_index, _index_metadata

    if _faiss_index is not None and _index_metadata is not None:
        return _faiss_index, _index_metadata

    try:
        from app.services.storage import workspace_path
        import faiss

        if wiki_type == "leading_practice":
            meta_dir = workspace_path("leading_practices") / "wiki" / ".meta"
        else:
            meta_dir = workspace_path(project_id) / "wiki" / ".meta"

        index_file = meta_dir / "embeddings.faiss"
        metadata_file = meta_dir / "embeddings_metadata.json"

        if not index_file.exists() or not metadata_file.exists():
            return None

        _faiss_index = faiss.read_index(str(index_file))
        _index_metadata = json.loads(metadata_file.read_text(encoding="utf-8"))

        return _faiss_index, _index_metadata

    except Exception as e:
        _LOG.debug(f"Embeddings index not available: {e}")
        return None


def _semantic_search(question: str, wiki_type: str, project_id: str | None, index: dict | None, top_k: int = 5) -> list:
    """Search wiki using semantic similarity via FAISS.

    Falls back to empty list if index not available (will use BM25 instead).
    """
    try:
        from sentence_transformers import SentenceTransformer

        global _embed_model
        if _embed_model is None:
            _embed_model = SentenceTransformer("all-MiniLM-L6-v2")

        index_data = _load_embeddings_index(wiki_type, project_id)
        if not index_data:
            return []

        faiss_idx, metadata = index_data
        q_emb = _embed_model.encode(question, convert_to_tensor=False).astype("float32").reshape(1, -1)

        # Search FAISS index
        distances, indices = faiss_idx.search(q_emb, min(top_k, metadata.get("count", 0)))

        # Map indices back to page_ids and fetch from index
        pages_map = {(p.get("page_id") or p.get("title", "").lower().replace(" ", "_")): p for p in (index.get("pages") or [])}
        results = []

        for idx in indices[0]:
            if idx >= 0 and idx < len(metadata.get("page_ids", [])):
                page_id = metadata["page_ids"][int(idx)]
                if page_id in pages_map:
                    results.append(pages_map[page_id])

        return results

    except ImportError:
        return []
    except Exception as e:
        _LOG.debug(f"Semantic search failed: {e}")
        return []


# ---------------------------------------------------------------------------
# Graph expansion — surface related pages via relationships + communities
# ---------------------------------------------------------------------------

def _expand_search_with_graph(primary_pages: list, wiki_type: str, project_id: str | None, index: dict | None) -> list:
    """Expand primary search results with related pages from relationships and communities.

    Takes top BM25/embedding results and adds:
    - 1-hop neighbors from relationships.json (parent/example/implements)
    - Community peers from communities.json

    Returns up to 12 enriched pages (primary + related).
    """
    if not primary_pages or not index:
        return primary_pages

    try:
        from app.services.storage import workspace_path
        import json

        if wiki_type == "leading_practice":
            meta_dir = workspace_path("leading_practices") / "wiki" / ".meta"
        else:
            meta_dir = workspace_path(project_id) / "wiki" / ".meta"

        # Load relationships and communities if available
        relationships = {}
        communities = {}

        rels_file = meta_dir / "relationships.json"
        if rels_file.exists():
            try:
                rels_data = json.loads(rels_file.read_text())
                # Index relationships by source_id for O(1) lookup
                for rel in (rels_data if isinstance(rels_data, list) else []):
                    src = rel.get("source_id")
                    if src:
                        if src not in relationships:
                            relationships[src] = []
                        relationships[src].append(rel)
            except Exception as e:
                _LOG.warning(f"Failed to load relationships: {e}")

        comm_file = meta_dir / "communities.json"
        if comm_file.exists():
            try:
                comm_data = json.loads(comm_file.read_text())
                # Index communities by page_id for O(1) lookup
                for page_id, comm_id in (comm_data.items() if isinstance(comm_data, dict) else []):
                    communities[page_id] = comm_id
            except Exception as e:
                _LOG.warning(f"Failed to load communities: {e}")

        # Collect primary page IDs
        primary_ids = set()
        for p in primary_pages:
            page_id = p.get("page_id") or p.get("title", "").lower().replace(" ", "_")
            primary_ids.add(page_id)

        # Expand with related pages
        related_ids = set()

        # 1. Add neighbors from relationships (prefer higher-confidence types)
        for page_id in primary_ids:
            if page_id in relationships:
                for rel in relationships[page_id]:
                    target = rel.get("target_id")
                    rel_type = rel.get("relation_type", "")
                    # Prefer semantically strong relationships
                    if target and rel_type in ("parent_of", "example_of", "implements", "refines"):
                        related_ids.add(target)

        # 2. Add community peers
        primary_community = None
        for page_id in primary_ids:
            if page_id in communities:
                primary_community = communities[page_id]
                break

        if primary_community is not None:
            for page_id, comm_id in communities.items():
                if comm_id == primary_community and page_id not in primary_ids:
                    related_ids.add(page_id)

        # Remove duplicates and fetch related page objects from index
        all_pages_map = {(p.get("page_id") or p.get("title", "").lower().replace(" ", "_")): p for p in (index.get("pages") or [])}

        result = primary_pages.copy()
        for related_id in related_ids:
            if related_id in all_pages_map and related_id not in primary_ids:
                result.append(all_pages_map[related_id])
                if len(result) >= 12:
                    break

        return result

    except Exception as e:
        _LOG.warning(f"Graph expansion failed, returning primary results only: {e}")
        return primary_pages


# ---------------------------------------------------------------------------
# BM25 + embedding rerank search
# ---------------------------------------------------------------------------

def _rerank_with_embeddings(question: str, candidates: list) -> list:
    """Rerank BM25 candidates using sentence-transformer cosine similarity. Falls back gracefully."""
    global _embed_model
    try:
        from sentence_transformers import SentenceTransformer, util
        if _embed_model is None:
            _embed_model = SentenceTransformer("all-MiniLM-L6-v2")
        q_emb = _embed_model.encode(question, convert_to_tensor=True)
        texts = [
            (p.get("title", "") + " " + p.get("content", "")[:500])
            for p in candidates
        ]
        c_embs = _embed_model.encode(texts, convert_to_tensor=True)
        scores = util.cos_sim(q_emb, c_embs)[0].tolist()
        ranked = sorted(zip(scores, candidates, strict=False), key=lambda x: -x[0])
        return [p for _, p in ranked[:5]]
    except ImportError:
        return candidates[:5]
    except Exception as e:
        _LOG.warning(f"Embedding rerank failed: {e}")
        return candidates[:5]


def _search_wiki_pages(question: str, index: dict, wiki_type: str, project_id) -> list:
    """Search wiki using semantic index (if available) + BM25, with embedding rerank and graph expansion."""
    pages = (index or {}).get("pages", [])
    if not pages:
        return []

    candidates = []

    # Try semantic search first (fast, finds conceptual matches)
    semantic_results = _semantic_search(question, wiki_type, project_id, index, top_k=10)
    if semantic_results:
        candidates.extend(semantic_results)
        _LOG.debug(f"Semantic search returned {len(semantic_results)} results")

    # If semantic search didn't return enough, supplement with BM25 keyword matching
    if len(candidates) < 5:
        try:
            from rank_bm25 import BM25Okapi
            corpus = [
                re.findall(r"\w+", (p.get("title", "") + " " + p.get("content", "")).lower())
                for p in pages
            ]
            query_tokens = re.findall(r"\w+", question.lower())
            scores = BM25Okapi(corpus).get_scores(query_tokens)
            ranked = sorted(zip(scores, pages, strict=False), key=lambda x: -x[0])
            bm25_results = [p for score, p in ranked[:20] if score > 0]

            # Deduplicate: add BM25 results not already in candidates
            candidate_ids = set(p.get("page_id") or p.get("title", "").lower().replace(" ", "_") for p in candidates)
            for p in bm25_results:
                page_id = p.get("page_id") or p.get("title", "").lower().replace(" ", "_")
                if page_id not in candidate_ids:
                    candidates.append(p)
                    candidate_ids.add(page_id)

        except ImportError:
            # Fallback to keyword overlap if rank_bm25 not installed
            stop_words = {"what","how","why","when","where","who","is","are","was","were","the","a","an","and","or","of","in","to","for","be","do","have","that","this","with","on","at","from","by","about"}
            q_words = set(re.findall(r"\w+", question.lower())) - stop_words
            scored = []
            for page in pages:
                text = (page.get("title","") + " " + page.get("content","")).lower()
                overlap = len(q_words & set(re.findall(r"\w+", text)))
                if overlap > 0:
                    scored.append((overlap, page))
            scored.sort(key=lambda x: -x[0])
            candidates.extend([p for _, p in scored[:20]])

    if not candidates:
        return []

    # Embedding rerank to top 5 (final ranking)
    primary_results = _rerank_with_embeddings(question, candidates)

    # Expand with related pages from graph (relationships + communities)
    return _expand_search_with_graph(primary_results, wiki_type, project_id, index)


# ---------------------------------------------------------------------------
# Answer synthesis
# ---------------------------------------------------------------------------

def _synthesize_answer(question: str, pages: list, wiki_type: str = "", project_id=None) -> str:
    """Synthesize an answer from relevant wiki pages using Claude.

    Pages are ordered: primary matches (top 5 from embedding rerank) then related pages
    (discovered via graph). The LLM is told which are which so it can weight them.
    """
    from app.services.claude import claude_generate, is_claude_enabled

    if not pages:
        return "No relevant wiki pages found to answer this question. Try ingesting some documents first."

    # Load schema for injection
    schema = ""
    if wiki_type:
        from app.services.wiki_ingest import _load_wiki_schema
        schema = _load_wiki_schema(wiki_type, project_id)
    schema_prefix = f"Wiki schema and conventions:\n{schema}\n\n" if schema else ""

    if not is_claude_enabled():
        # Fallback: concatenate excerpts
        parts = []
        for page in pages[:3]:
            parts.append(f"**{page.get('title', 'Unknown')}**\n{page.get('content', '')[:300]}")
        return "\n\n".join(parts)

    # Annotate primary (top 5) vs related (6+) pages
    context_parts = []
    for i, p in enumerate(pages[:5]):
        context_parts.append(
            f"### {p.get('title', 'Unknown')} [PRIMARY]\n{p.get('content', '')[:800]}"
        )

    if len(pages) > 5:
        context_parts.append("\n**Related pages from knowledge graph:**\n")
        for p in pages[5:12]:
            context_parts.append(
                f"### {p.get('title', 'Unknown')} [RELATED]\n{p.get('content', '')[:500]}"
            )

    context = "\n\n".join(context_parts)

    return claude_generate(
        system=(
            schema_prefix
            + "You are a knowledgeable assistant answering questions from a curated wiki. "
            "Primary pages are direct matches to the query. Related pages are connected via the knowledge graph "
            "(relationships, communities) and may provide context or alternative perspectives.\n"
            "Prioritize primary pages but incorporate related pages if they add depth. "
            "Be concise and direct. "
            "Cite the page titles inline using wiki-link syntax, e.g. [[Page Title]] or [[page_id|Page Title]]. "
            "If the pages don't contain relevant information, say so clearly."
        ),
        user=f"Question: {question}\n\nWiki pages:\n{context}",
        max_tokens=1024,
    )


# ---------------------------------------------------------------------------
# Citation parsing
# ---------------------------------------------------------------------------

def _extract_citations(answer: str, pages: list) -> list:
    """Parse [[Page Title]] and [[page_id|Label]] links from synthesized answer to build citations.

  Does not fabricate citations when the LLM omitted wiki-link syntax — only pages
  explicitly linked or strongly overlapping the answer text are returned.
    """
    from app.core.pdf_extract import citation_overlap_score

    cited_titles = set(re.findall(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]", answer))
    page_map = {p.get("title", "").lower(): p for p in pages}
    cited = [page_map[t.lower()] for t in cited_titles if t.lower() in page_map]
    if not cited and pages and (answer or "").strip():
        ranked = sorted(
            ((citation_overlap_score(answer, p), p) for p in pages),
            key=lambda x: x[0],
            reverse=True,
        )
        cited = [p for score, p in ranked if score >= 0.15][:3]
    return [
        {
            "page_id": p.get("page_id", ""),
            "page_title": p.get("title", "Unknown"),
            "context": p.get("content", "")[:200],
        }
        for p in cited
    ]


# ---------------------------------------------------------------------------
# Answer quality evaluation
# ---------------------------------------------------------------------------

def _evaluate_answer_quality(answer: str, pages: list, question: str) -> dict | None:
    """Lightweight quality check on the synthesized answer."""
    from app.services.claude import claude_generate_json, is_claude_enabled

    if not is_claude_enabled() or not answer or not pages:
        return None

    try:
        result = claude_generate_json(
            system="You are a QA reviewer. Return strict JSON only.",
            user=(
                f"Question: {question}\n\nAnswer: {answer}\n\n"
                "Rate the answer. Return JSON: "
                '{"quality_score": 0-100, "issues": ["..."], "suggestions": ["..."]}'
            ),
            max_tokens=512,
        )
        return {
            "quality_score": result.get("quality_score", 0),
            "issues": result.get("issues", []),
            "suggestions": result.get("suggestions", []),
        }
    except Exception as e:
        _LOG.warning(f"Answer QA evaluation failed: {e}")
        return None
