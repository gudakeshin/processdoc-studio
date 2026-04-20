"""
wiki_query.py — Wiki query helpers.

Handles wiki index loading, BM25 + embedding-rerank search, answer synthesis,
citation parsing, and answer quality evaluation.
"""
import re
import logging
from typing import Optional

_LOG = logging.getLogger(__name__)
_embed_model = None


# ---------------------------------------------------------------------------
# Index loading
# ---------------------------------------------------------------------------

def _get_wiki_index(wiki_type: str, project_id: Optional[str]) -> Optional[dict]:
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
            except Exception:
                continue

        return {"pages": pages}
    except Exception as e:
        _LOG.error(f"Error building wiki index: {e}")
        return {"pages": []}


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
        ranked = sorted(zip(scores, candidates), key=lambda x: -x[0])
        return [p for _, p in ranked[:5]]
    except ImportError:
        return candidates[:5]
    except Exception as e:
        _LOG.warning(f"Embedding rerank failed: {e}")
        return candidates[:5]


def _search_wiki_pages(question: str, index: dict, wiki_type: str, project_id) -> list:
    """BM25 search over wiki index, with embedding rerank for top candidates."""
    pages = (index or {}).get("pages", [])
    if not pages:
        return []
    try:
        from rank_bm25 import BM25Okapi
        corpus = [
            re.findall(r"\w+", (p.get("title", "") + " " + p.get("content", "")).lower())
            for p in pages
        ]
        query_tokens = re.findall(r"\w+", question.lower())
        scores = BM25Okapi(corpus).get_scores(query_tokens)
        ranked = sorted(zip(scores, pages), key=lambda x: -x[0])
        candidates = [p for score, p in ranked[:20] if score > 0]
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
        candidates = [p for _, p in scored[:20]]

    if not candidates:
        return []
    return _rerank_with_embeddings(question, candidates)


# ---------------------------------------------------------------------------
# Answer synthesis
# ---------------------------------------------------------------------------

def _synthesize_answer(question: str, pages: list, wiki_type: str = "", project_id=None) -> str:
    """Synthesize an answer from relevant wiki pages using Claude."""
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

    context = "\n\n".join(
        f"### {p.get('title', 'Unknown')}\n{p.get('content', '')[:800]}"
        for p in pages[:5]
    )

    return claude_generate(
        system=(
            schema_prefix
            + "You are a knowledgeable assistant answering questions from a curated wiki. "
            "Use only the provided wiki pages to answer. Be concise and direct. "
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
    Falls back to all source pages if the LLM didn't use wiki-link syntax."""
    cited_titles = set(re.findall(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]", answer))
    page_map = {p.get("title", "").lower(): p for p in pages}
    cited = [page_map[t.lower()] for t in cited_titles if t.lower() in page_map]
    if not cited:
        cited = pages[:5]
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

def _evaluate_answer_quality(answer: str, pages: list, question: str) -> Optional[dict]:
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
