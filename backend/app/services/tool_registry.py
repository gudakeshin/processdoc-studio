from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import re
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.services.observability import increment
from app.services.storage import workspace_path
from app.services.swarm_tool_handlers import (
    swarm_broadcast,
    swarm_create_task,
    swarm_list_messages,
    swarm_list_tasks,
    swarm_send_message,
    swarm_update_task,
)
from app.services.web_capture import web_capture as _web_capture_impl

ToolHandler = Callable[..., Any]
_LOG = logging.getLogger(__name__)

_JSON_OBJECT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": True,
}

# ---------------------------------------------------------------------------
# Semantic retrieval engine (singleton, lazy-loaded)
# ---------------------------------------------------------------------------

_EMBED_LOCK = threading.Lock()
_EMBED_MODEL: Any = None          # sentence_transformers.SentenceTransformer | None
_EMBED_MODEL_LOAD_FAILED = False  # set True after a load failure; prevents repeated retries

# Per-project embedding cache:
#   _CHUNK_CACHE[project_id] = {"mtime_sig": str, "chunks": list[str], "sources": list[str], "matrix": np.ndarray}
_CHUNK_CACHE: dict[str, dict[str, Any]] = {}
_CACHE_LOCK = threading.Lock()

_EMBED_MODEL_NAME = "all-MiniLM-L6-v2"  # 22 MB, ~5 ms/query on CPU


def _get_embed_model() -> Any:
    """Lazy-load SentenceTransformer model; returns None on failure."""
    global _EMBED_MODEL, _EMBED_MODEL_LOAD_FAILED
    if _EMBED_MODEL is not None:
        return _EMBED_MODEL
    if _EMBED_MODEL_LOAD_FAILED:
        return None
    with _EMBED_LOCK:
        if _EMBED_MODEL is not None:
            return _EMBED_MODEL
        if _EMBED_MODEL_LOAD_FAILED:
            return None
        try:
            from sentence_transformers import SentenceTransformer  # type: ignore
            _EMBED_MODEL = SentenceTransformer(_EMBED_MODEL_NAME)
            _LOG.info("tool_registry: semantic retrieval model '%s' loaded", _EMBED_MODEL_NAME)
        except Exception as exc:
            _EMBED_MODEL_LOAD_FAILED = True
            _LOG.warning("tool_registry: failed to load embedding model (%s); falling back to lexical", exc)
    return _EMBED_MODEL


def _mtime_signature(parsed_dir: Path) -> str:
    """Stable signature of all .json mtime values in parsed_dir."""
    parts = sorted(
        f"{p.name}:{p.stat().st_mtime_ns}"
        for p in parsed_dir.glob("*.json")
        if p.is_file()
    )
    return hashlib.md5("|".join(parts).encode(), usedforsecurity=False).hexdigest()


def _load_chunks(parsed_dir: Path) -> tuple[list[str], list[str]]:
    """Load all text chunks and their source filenames from parsed_dir."""
    chunks: list[str] = []
    sources: list[str] = []
    for item in sorted(parsed_dir.glob("*.json")):
        try:
            data = json.loads(item.read_text(encoding="utf-8"))
        except Exception:  # noqa: S112 — best-effort, non-fatal
            continue
        for chunk in (data.get("chunks", []) if isinstance(data, dict) else []):
            if isinstance(chunk, str) and chunk.strip():
                chunks.append(chunk)
                sources.append(item.name)
    return chunks, sources


def _get_project_embeddings(project_id: str, parsed_dir: Path, model: Any) -> dict[str, Any] | None:
    """
    Return cached (or freshly computed) chunk embeddings for a project.
    Re-encodes only when parsed_doc files have changed (mtime signature).
    """
    sig = _mtime_signature(parsed_dir)
    with _CACHE_LOCK:
        cached = _CHUNK_CACHE.get(project_id)
        if cached and cached.get("mtime_sig") == sig:
            return cached
    # Rebuild cache outside lock (encoding can take ~100-500 ms for large corpora)
    chunks, sources = _load_chunks(parsed_dir)
    if not chunks:
        return None
    try:
        import numpy as np
        matrix = model.encode(chunks, convert_to_numpy=True, show_progress_bar=False)
        # L2-normalise for cosine similarity via dot product
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        norms = np.where(norms == 0, 1.0, norms)
        matrix = matrix / norms
        entry: dict[str, Any] = {"mtime_sig": sig, "chunks": chunks, "sources": sources, "matrix": matrix}
        with _CACHE_LOCK:
            _CHUNK_CACHE[project_id] = entry
        return entry
    except Exception as exc:
        _LOG.warning("tool_registry: chunk encoding failed (%s)", exc)
        return None


def _semantic_retrieve(query: str, project_id: str, parsed_dir: Path, top_k: int = 8) -> list[dict[str, Any]]:
    """
    Semantic retrieval: encode query, compute cosine similarity against all
    project chunk embeddings, return top_k results sorted by similarity.
    """
    model = _get_embed_model()
    if model is None:
        return []
    cache = _get_project_embeddings(project_id, parsed_dir, model)
    if cache is None:
        return []
    try:
        import numpy as np
        qvec = model.encode([query], convert_to_numpy=True, show_progress_bar=False)[0]
        norm = float(np.linalg.norm(qvec))
        if norm > 0:
            qvec = qvec / norm
        scores = cache["matrix"].dot(qvec).tolist()
        ranked = sorted(
            zip(scores, cache["sources"], cache["chunks"], strict=False),
            key=lambda x: x[0],
            reverse=True,
        )
        return [
            {"source": src, "score": round(float(sc), 4), "text": chunk[:1000]}
            for sc, src, chunk in ranked[:top_k]
            if float(sc) > 0.20   # discard near-zero similarity matches
        ]
    except Exception as exc:
        _LOG.warning("tool_registry: semantic scoring failed (%s)", exc)
        return []


def _lexical_retrieve(query: str, parsed_dir: Path, top_k: int = 8) -> list[dict[str, Any]]:
    """
    Fallback BM25-lite lexical retrieval (original implementation).
    Used when the embedding model is unavailable.
    """
    terms = {t for t in re.split(r"[^a-zA-Z0-9]+", query.lower()) if len(t) > 2}
    scored: list[tuple[float, str, str]] = []
    for item in parsed_dir.glob("*.json"):
        try:
            data = json.loads(item.read_text(encoding="utf-8"))
        except Exception:  # noqa: S112 — best-effort, non-fatal
            continue
        for chunk in (data.get("chunks", []) if isinstance(data, dict) else []):
            if not isinstance(chunk, str) or not chunk.strip():
                continue
            lowered = chunk.lower()
            score = sum(1 for t in terms if t in lowered)
            if score > 0:
                scored.append((float(score), item.name, chunk))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [
        {"source": src, "score": round(sc, 4), "text": chunk[:1000]}
        for sc, src, chunk in scored[:top_k]
    ]


def retrieve_context(*_: Any, **__: Any) -> dict[str, Any]:
    """
    Retrieve relevant document chunks using semantic similarity (cosine distance
    on all-MiniLM-L6-v2 embeddings). Falls back to lexical BM25-lite overlap
    when the embedding model is unavailable.

    Returns top 8 chunks (vs. original 5) with similarity scores, plus a
    concatenated context_text string capped at 8 000 characters.
    """
    query = __.get("query") if "query" in __ else (_[0] if _ else "")
    project_id = __.get("project_id")
    if not query or not project_id:
        return {"chunks": [], "context_text": "", "retrieval_method": "none"}
    parsed_dir = workspace_path(str(project_id)) / "parsed_docs"
    if not parsed_dir.exists():
        return {"chunks": [], "context_text": "", "retrieval_method": "none"}

    results = _semantic_retrieve(str(query), str(project_id), parsed_dir)
    method = "semantic"
    if not results:
        results = _lexical_retrieve(str(query), parsed_dir)
        method = "lexical"

    return {
        "chunks": results,
        "context_text": "\n\n".join(r["text"] for r in results)[:8000],
        "retrieval_method": method,
    }


def _format_search_results(
    results: list[dict[str, Any]],
    *,
    source_label: str,
    url_key: str | None = None,
    snippet_key: str = "snippet",
    title_key: str = "title",
    score_key: str | None = None,
) -> str:
    """Format a list of search-result dicts into a numbered human-readable string."""
    if not results:
        return f"No {source_label} results found."
    lines: list[str] = [f"{source_label} results ({len(results)} found):\n"]
    for i, r in enumerate(results, 1):
        title = str(r.get(title_key) or "Untitled")
        snippet = str(r.get(snippet_key) or "")[:500]
        parts = [f"[{i}] {title}"]
        if url_key and r.get(url_key):
            parts.append(f"URL: {r[url_key]}")
        if score_key and r.get(score_key) is not None:
            parts.append(f"Score: {r[score_key]:.3f}")
        parts.append(snippet)
        lines.append("\n".join(parts))
    return "\n\n".join(lines)


def web_capture(*_: Any, **__: Any) -> dict[str, Any]:
    """web_capture(url, max_chars?, max_bytes?, timeout?): SSRF-safe HTTPS fetch.

    Returns a structured dict with ``ok``, ``title``, ``text``, ``text_chars``,
    ``truncated``, ``content_type``, and ``error`` keys so agents can reason
    about the capture without parsing a free-form string. Only ``https://`` URLs
    are accepted; private/loopback/metadata addresses are blocked.
    """

    url = __.get("url") if "url" in __ else (_[0] if _ else None)
    kwargs: dict[str, Any] = {}
    if "max_chars" in __ and __["max_chars"] is not None:
        with contextlib.suppress(TypeError, ValueError):
            kwargs["max_chars"] = int(__["max_chars"])
    if "max_bytes" in __ and __["max_bytes"] is not None:
        with contextlib.suppress(TypeError, ValueError):
            kwargs["max_bytes"] = int(__["max_bytes"])
    if "timeout" in __ and __["timeout"] is not None:
        with contextlib.suppress(TypeError, ValueError):
            kwargs["timeout"] = float(__["timeout"])
    try:
        return _web_capture_impl(url, **kwargs)
    except Exception as exc:  # final safety net; tool must never crash the loop
        _LOG.warning("web_capture tool handler failed: %s", exc)
        return {
            "url": str(url or ""),
            "ok": False,
            "title": "",
            "text": "",
            "text_chars": 0,
            "truncated": False,
            "content_type": "",
            "error": f"web_capture error: {exc}",
        }


def web_search(*_: Any, **__: Any) -> str:
    """web_search implementation (Brave primary; optional Google fallback).

    Returns a formatted string so agents can read results directly.
    """
    query = __.get("query") if "query" in __ else None
    project_id = __.get("project_id")
    if query is None and _:
        query = _[0]

    try:
        from app.services.web_search import web_search_service

        if query is None:
            return "No query provided."
        results = web_search_service.search(str(query), project_id=project_id)
        return _format_search_results(results, source_label="Web search", url_key="url")
    except Exception:
        return "Web search unavailable."


def search_leading_practices(*_: Any, **__: Any) -> str:
    """search_leading_practices(query): LP library retrieval.

    Returns a formatted string so agents can read results directly.
    """
    query = __.get("query") if "query" in __ else None
    project_id = __.get("project_id")
    if query is None and _:
        query = _[0]

    if query is None:
        return "No query provided."

    try:
        from app.services.leading_practices import leading_practice_library_service

        results = leading_practice_library_service.search(str(query), project_id=project_id)
        return _format_search_results(
            results,
            source_label="Leading Practice Library",
            snippet_key="text",
            title_key="heading",
            score_key="relevance_score",
        )
    except Exception:
        return "Leading practice search unavailable."


def search_wiki(*_: Any, **__: Any) -> str:
    """search_wiki(query): BM25 search over project wiki pages.

    Returns a formatted string so agents can read results directly.
    """
    query = __.get("query") if "query" in __ else None
    project_id = __.get("project_id")
    max_results = int(__.get("max_results") or 8)
    if query is None and _:
        query = _[0]
    if query is None:
        return "No query provided."
    try:
        from app.services.wiki_operations import search_wiki as _search_wiki

        results = _search_wiki(str(query), project_id=project_id, max_results=max_results)
        return _format_search_results(results, source_label="Project Wiki", score_key="score")
    except Exception:
        return "Wiki search unavailable."


def validate_references(*_: Any, **__: Any) -> dict[str, Any]:
    text = str(__.get("text") if "text" in __ else (_[0] if _ else ""))
    issues: list[str] = []
    has_reference_marker = bool(re.search(r"\[\d+\]|\(source:[^)]+\)|https?://\S+", text, flags=re.IGNORECASE))
    if not has_reference_marker:
        issues.append("No explicit source/citation marker found.")
    broken_http = re.findall(r"https?://[^\s)\]]+", text)
    if len(broken_http) > 25:
        issues.append("Unusually high number of links; verify references are relevant.")
    return {"passed": len(issues) == 0, "issues": issues}


def check_brand_compliance(*_: Any, **__: Any) -> dict[str, Any]:
    text = str(__.get("text") if "text" in __ else (_[0] if _ else ""))
    banned = ("best-in-class", "guaranteed", "revolutionary", "unprecedented")
    issues = [f"Promotional phrase found: {phrase}" for phrase in banned if phrase in text.lower()]
    long_lines = [ln for ln in text.splitlines() if len(ln.split()) > 55]
    if long_lines:
        issues.append("Detected very long sentences; readability may violate style profile.")
    return {"passed": len(issues) == 0, "issues": issues}


def memory_lookup(*_: Any, **__: Any) -> dict[str, Any]:
    """Skill-card alias for **document chunk retrieval** only (same as ``retrieve_context``).

    It does **not** query ``MemoryItem`` rows from the Memory page; use ``memory_items`` for that.
    """
    return retrieve_context(*_, **__)


def memory_items(*_: Any, **__: Any) -> dict[str, Any]:
    """Load structured ``MemoryItem`` rows for the project (Memory page / long-term facts)."""
    project_id = __.get("project_id")
    if not project_id:
        return {"items": [], "error": "project_id required", "count": 0}
    raw_limit = __.get("limit", 25)
    try:
        lim = max(1, min(40, int(raw_limit)))
    except (TypeError, ValueError):
        lim = 25
    from sqlalchemy import select

    from app.core.config import settings as app_settings
    from app.db.models import MemoryItem
    from app.db.session import SessionLocal
    from app.services.memory_consent import memory_item_allowed_for_use

    session = SessionLocal()
    try:
        rows = session.scalars(
            select(MemoryItem)
            .where(MemoryItem.project_id == str(project_id), MemoryItem.is_archived.is_(False))
            .order_by(MemoryItem.updated_at.desc())
            .limit(lim)
        ).all()
        out: list[dict[str, Any]] = []
        skipped = 0
        ledger_skipped = 0
        ledger_on = bool(app_settings.memory_enforce_consent_ledger)
        for it in rows:
            ok, reason = memory_item_allowed_for_use(
                session,
                str(project_id),
                it,
                respect_consent=app_settings.memory_respect_consent_in_context,
                enforce_consent_ledger=ledger_on,
            )
            if not ok:
                if reason == "consent_field":
                    skipped += 1
                elif reason == "consent_ledger":
                    ledger_skipped += 1
                continue
            out.append(
                {
                    "memory_type": it.memory_type,
                    "key": it.key,
                    "value": it.value,
                    "confidence": it.confidence,
                    "source": it.source,
                    "consent_state": it.consent_state,
                    "principal_id": it.principal_id,
                }
            )
        if skipped:
            increment("memory_items_consent_skipped_total", skipped)
        if ledger_skipped:
            increment("memory_items_ledger_blocked_total", ledger_skipped)
        return {"items": out, "count": len(out)}
    finally:
        session.close()


def drawio_process_model_to_xml(*_: Any, **__: Any) -> dict[str, Any]:
    process_model = __.get("process_model")
    if process_model is None and _:
        process_model = _[0]
    try:
        from app.services.drawio_builder import process_model_to_drawio_xml

        xml = process_model_to_drawio_xml(process_model if isinstance(process_model, dict) else {})
        return {"xml": xml}
    except Exception:
        return {"xml": ""}


def document_builder(*_: Any, **__: Any) -> dict[str, Any]:
    """
    document_builder — validates and normalises a structured Markdown document
    intended for DOCX export.

    Checks that the document has an H1 title, required H2 sections (Purpose, Scope,
    Roles, Procedure, References), and that the Procedure section contains numbered
    steps. Returns a normalised pass/fail report with specific issues.

    Does NOT modify the document; the agent must re-generate to fix issues.
    """
    text = str(__.get("text") if "text" in __ else (_[0] if _ else ""))
    issues: list[str] = []
    if not text.strip():
        return {"passed": False, "issues": ["Empty document."], "normalised": text}
    lines = text.splitlines()
    h1_lines = [ln for ln in lines if ln.startswith("# ") and not ln.startswith("## ")]
    if not h1_lines:
        issues.append("Missing H1 title (line starting with '# ').")
    required_h2 = ["purpose", "scope", "roles", "procedure"]
    present_h2 = {ln.lstrip("#").strip().lower() for ln in lines if ln.startswith("## ")}
    for sec in required_h2:
        if not any(sec in h for h in present_h2):
            issues.append(f"Missing required section: '## {sec.capitalize()}'.")
    numbered = re.findall(r"^\s*\d+\.", text, flags=re.MULTILINE)
    if len(numbered) < 2:
        issues.append("Procedure section has fewer than 2 numbered steps.")
    return {"passed": len(issues) == 0, "issues": issues}


def diagram_builder(*_: Any, **__: Any) -> dict[str, Any]:
    """
    diagram_builder — validates mxGraphModel XML structure for diagrams.net export.

    Checks for required scaffolding cells (id=0, id=1), presence of vertex cells
    (process steps), edge cells (connections), and optionally decision rhombus cells.
    Returns a pass/fail report with structural issues.

    Does NOT modify the XML; the agent must re-generate to fix issues.
    """
    xml = str(__.get("xml") if "xml" in __ else (__. get("text") if "text" in __ else (_[0] if _ else "")))
    issues: list[str] = []
    if not xml.strip():
        return {"passed": False, "issues": ["Empty XML."]}
    if "<mxGraphModel" not in xml:
        issues.append("Missing <mxGraphModel> root element.")
        return {"passed": False, "issues": issues}
    if 'id="0"' not in xml and "id='0'" not in xml:
        issues.append("Missing required scaffolding cell id='0' (root).")
    if 'id="1"' not in xml and "id='1'" not in xml:
        issues.append("Missing required scaffolding cell id='1' (default layer).")
    vertex_count = len(re.findall(r'vertex=["\']1["\']', xml))
    if vertex_count < 1:
        issues.append("No vertex cells found — at least one step node is required.")
    edge_count = len(re.findall(r'edge=["\']1["\']', xml))
    if vertex_count > 1 and edge_count < 1:
        issues.append("Multiple vertices exist but no edge cells found — steps are unconnected.")
    return {"passed": len(issues) == 0, "issues": issues, "vertex_count": vertex_count, "edge_count": edge_count}


def table_builder(*_: Any, **__: Any) -> dict[str, Any]:
    """
    table_builder — validates a GitHub-flavored Markdown table.

    Checks for a header row, separator row, at least one data row, consistent
    column counts, and the absence of blank cells (every cell must have content
    or an explicit '—' placeholder).

    Does NOT modify the table; the agent must re-generate to fix issues.
    """
    text = str(__.get("text") if "text" in __ else (_[0] if _ else ""))
    issues: list[str] = []
    if not text.strip():
        return {"passed": False, "issues": ["Empty table."]}
    table_lines = [ln.strip() for ln in text.splitlines() if ln.strip().startswith("|")]
    if not table_lines:
        return {"passed": False, "issues": ["No table rows found (lines starting with '|')."]}
    if len(table_lines) < 3:
        issues.append(f"Table has only {len(table_lines)} row(s); need header + separator + ≥1 data row.")
    sep_candidates = [ln for ln in table_lines if re.match(r"^\|[\s\-:]+(\|[\s\-:]+)*\|?$", ln)]
    if not sep_candidates:
        issues.append("Missing separator row (e.g. |---|---|).")
    header_cols = len(table_lines[0].split("|")) - 2 if table_lines else 0
    for i, row in enumerate(table_lines[2:], start=3):
        cols = len(row.split("|")) - 2
        if cols != header_cols:
            issues.append(f"Row {i} has {cols} column(s) but header has {header_cols}.")
        blank_cells = [c.strip() for c in row.split("|")[1:-1] if not c.strip()]
        if blank_cells:
            issues.append(f"Row {i} has {len(blank_cells)} blank cell(s) — use '—' for empty values.")
    return {
        "passed": len(issues) == 0,
        "issues": issues,
        "row_count": max(0, len(table_lines) - 2),
        "column_count": header_cols,
    }


def cross_reference_checker(*_: Any, **__: Any) -> dict[str, Any]:
    """
    cross_reference_checker — verifies that role names and step names mentioned
    in a generated document match the ProcessModel source of truth.

    Helps catch hallucinated roles (e.g. 'Chief Risk Officer' when ProcessModel
    has 'Compliance Lead') or fabricated steps not in the ProcessModel.

    Returns {"passed": bool, "unmatched_roles": list[str], "unmatched_steps": list[str]}.
    """
    text = str(__.get("text") if "text" in __ else (_[0] if _ else ""))
    process_model = __.get("process_model") if "process_model" in __ else None
    if not isinstance(process_model, dict):
        return {"passed": True, "unmatched_roles": [], "unmatched_steps": [], "note": "No process_model provided."}
    known_roles = {str(r).lower().strip() for r in (process_model.get("roles") or [])}
    known_steps = {str(s.get("name") or "").lower().strip() for s in (process_model.get("steps") or []) if isinstance(s, dict)}
    lowered = text.lower()
    unmatched_roles: list[str] = []
    unmatched_steps: list[str] = []
    # Check that all known roles appear at least once in the text
    for role in known_roles:
        if role and role not in lowered:
            unmatched_roles.append(role)
    # Spot-check step names: flag known steps that are entirely absent
    for step in known_steps:
        # Use first 3 significant words as a probe to avoid false positives from rephrasing
        probe_words = [w for w in step.split() if len(w) > 3][:3]
        if probe_words and not all(w in lowered for w in probe_words):
            unmatched_steps.append(step)
    return {
        "passed": len(unmatched_roles) == 0 and len(unmatched_steps) == 0,
        "unmatched_roles": unmatched_roles,
        "unmatched_steps": unmatched_steps,
    }


def format_table(*_: Any, **__: Any) -> dict[str, Any]:
    """
    format_table — converts ProcessModel step data into a clean Markdown table
    with caller-specified columns.

    Input:
      process_model: dict  — the ProcessModel JSON object
      columns: list[str]   — subset of: Activity, Owner, Inputs, Outputs, Tools, Duration, Notes

    Returns {"markdown": str} — the formatted table, ready to embed in a document.
    This saves agents from doing fragile inline table construction.
    """
    process_model = __.get("process_model") if "process_model" in __ else None
    columns = __.get("columns") or ["Activity", "Owner", "Inputs", "Outputs", "Tools", "Duration", "Notes"]
    if not isinstance(process_model, dict):
        return {"markdown": "| (No ProcessModel provided) |", "error": "Missing process_model parameter."}
    steps = process_model.get("steps") or []
    roles = process_model.get("roles") or []
    col_getters: dict[str, Any] = {
        "Activity": lambda s: s.get("name") or "—",
        "Owner": lambda s: s.get("role") or (roles[0] if roles else "TBD"),
        "Inputs": lambda s: ", ".join(s.get("inputs") or []) or "—",
        "Outputs": lambda s: ", ".join(s.get("outputs") or []) or "—",
        "Tools": lambda s: ", ".join(s.get("tools") or []) or "—",
        "Duration": lambda s: s.get("duration_estimate") or "—",
        "Notes": lambda s: s.get("notes") or "—",
    }
    valid_cols = [c for c in columns if c in col_getters]
    if not valid_cols:
        return {"markdown": "| (No valid columns specified) |", "error": f"Unknown columns: {columns}"}
    header = "| " + " | ".join(valid_cols) + " |"
    sep = "|" + "|".join("---" for _ in valid_cols) + "|"
    rows = [header, sep]
    for step in steps:
        if not isinstance(step, dict):
            continue
        cells = [str(col_getters[c](step)).replace("|", "\\|")[:200] for c in valid_cols]
        rows.append("| " + " | ".join(cells) + " |")
    if len(rows) == 2:
        rows.append("| " + " | ".join("—" for _ in valid_cols) + " |  ← No steps in ProcessModel")
    return {"markdown": "\n".join(rows)}


def save_draft(*_: Any, **__: Any) -> dict[str, Any]:
    """
    save_draft — persist an intermediate draft to the project workspace so it
    can be retrieved in a later tool-loop round or after a quality gate failure.

    This enables a multi-round revision pattern:
      Round 1: generate draft → save_draft(key='v1', content=...)
      Round 2: load_draft(key='v1') → validate → save_draft(key='v2', content=...)
      Final:   load_draft(key='v2') → return as output

    Files are stored at:
      {workspace_root}/{project_id}/runs/{run_id}/drafts/{agent_id}_{key}.md
    or
      {workspace_root}/{project_id}/drafts/{agent_id}_{key}.md  (if no run_id)

    Returns {"saved": True, "path": str} on success, {"saved": False, "error": str} on failure.
    """
    content = str(__.get("content") if "content" in __ else (_[0] if _ else ""))
    key = str(__.get("key") or "draft")
    project_id = str(__.get("project_id") or "")
    run_id = str(__.get("run_id") or "")
    agent_id = str(__.get("agent_id") or "agent")
    swarm_tm = str(__.get("swarm_teammate_id") or "").strip()

    if not content.strip():
        return {"saved": False, "error": "Content is empty — nothing to save."}
    if not project_id:
        return {"saved": False, "error": "project_id is required."}

    try:
        base = workspace_path(project_id)
        # Sanitise filename: allow only alphanumeric, dash, underscore
        safe_agent = re.sub(r"[^a-zA-Z0-9_\-]", "_", agent_id)[:32]
        safe_key = re.sub(r"[^a-zA-Z0-9_\-]", "_", key)[:64]
        if (
            bool(getattr(settings, "swarm_orchestration_enabled", False))
            and swarm_tm
            and run_id
        ):
            from app.services.swarm import teammate_workspace_dir

            draft_dir = teammate_workspace_dir(project_id, run_id, swarm_tm) / "drafts"
        elif run_id:
            draft_dir = base / "runs" / run_id / "drafts"
        else:
            draft_dir = base / "drafts"
        draft_dir.mkdir(parents=True, exist_ok=True)
        filepath = draft_dir / f"{safe_agent}_{safe_key}.md"
        filepath.write_text(content, encoding="utf-8")
        return {"saved": True, "path": str(filepath), "bytes": len(content.encode("utf-8"))}
    except Exception as exc:
        return {"saved": False, "error": str(exc)[:400]}


def load_draft(*_: Any, **__: Any) -> dict[str, Any]:
    """
    load_draft — retrieve a previously saved intermediate draft from the project
    workspace. Complements save_draft for multi-round revision workflows.

    Returns {"found": True, "content": str, "path": str} if the draft exists,
    or {"found": False, "error": str} if not found or unreadable.
    """
    key = str(__.get("key") or "draft")
    project_id = str(__.get("project_id") or "")
    run_id = str(__.get("run_id") or "")
    agent_id = str(__.get("agent_id") or "agent")
    swarm_tm = str(__.get("swarm_teammate_id") or "").strip()

    if not project_id:
        return {"found": False, "error": "project_id is required."}

    try:
        base = workspace_path(project_id)
        safe_agent = re.sub(r"[^a-zA-Z0-9_\-]", "_", agent_id)[:32]
        safe_key = re.sub(r"[^a-zA-Z0-9_\-]", "_", key)[:64]
        # Look in teammate sandbox first, then run-scoped, then project-level drafts dir
        candidates: list[Path] = []
        if (
            bool(getattr(settings, "swarm_orchestration_enabled", False))
            and swarm_tm
            and run_id
        ):
            from app.services.swarm import teammate_workspace_dir

            candidates.append(
                teammate_workspace_dir(project_id, run_id, swarm_tm) / "drafts" / f"{safe_agent}_{safe_key}.md"
            )
        if run_id:
            candidates.append(base / "runs" / run_id / "drafts" / f"{safe_agent}_{safe_key}.md")
        candidates.append(base / "drafts" / f"{safe_agent}_{safe_key}.md")

        for filepath in candidates:
            if filepath.exists():
                content = filepath.read_text(encoding="utf-8")
                return {"found": True, "content": content, "path": str(filepath), "bytes": len(content.encode("utf-8"))}

        return {"found": False, "error": f"No draft found for agent='{agent_id}' key='{key}'."}
    except Exception as exc:
        return {"found": False, "error": str(exc)[:400]}


def process_model_query(*_: Any, **__: Any) -> dict[str, Any]:
    """
    process_model_query — structured query interface for ProcessModel data.

    Rather than parsing the full ProcessModel JSON blob each time, agents
    can use this tool to fetch specific subsets efficiently. Reduces prompt
    size and prevents the LLM from misreading deeply nested JSON.

    filter_type options:
      "all_steps"           → returns all steps with full fields
      "all_roles"           → returns the roles list
      "all_decisions"       → returns all decision branches
      "steps_by_role"       → steps where step.role matches filter_value (case-insensitive)
      "step_by_id"          → single step matching filter_value exactly (e.g. "s3")
      "steps_containing"    → steps whose name contains filter_value (case-insensitive)
      "swimlane"            → swimlane mapping for filter_value role; all swimlanes if omitted
      "metadata"            → the metadata dict
      "summary"             → process_name + role count + step count + decision count

    Returns {"result": ..., "count": int} or {"error": str}.
    """
    process_model = __.get("process_model") if "process_model" in __ else None
    if process_model is None and _:
        process_model = _[0]
    filter_type = str(__.get("filter_type") or "all_steps").strip().lower()
    filter_value = str(__.get("filter_value") or "").strip()

    if not isinstance(process_model, dict):
        return {"error": "process_model parameter is required and must be a JSON object."}

    steps: list[dict] = [s for s in (process_model.get("steps") or []) if isinstance(s, dict)]
    roles: list[str] = [str(r) for r in (process_model.get("roles") or [])]
    decisions: list[dict] = [d for d in (process_model.get("decisions") or []) if isinstance(d, dict)]
    swimlanes: dict = process_model.get("swimlanes") or {}
    metadata: dict = process_model.get("metadata") or {}
    name: str = str(process_model.get("process_name") or "")

    if filter_type == "all_steps":
        return {"result": steps, "count": len(steps)}

    elif filter_type == "all_roles":
        return {"result": roles, "count": len(roles)}

    elif filter_type == "all_decisions":
        return {"result": decisions, "count": len(decisions)}

    elif filter_type == "steps_by_role":
        if not filter_value:
            return {"error": "filter_value required for filter_type='steps_by_role'."}
        fv = filter_value.lower()
        matched = [s for s in steps if fv in str(s.get("role") or "").lower()]
        return {"result": matched, "count": len(matched)}

    elif filter_type == "step_by_id":
        if not filter_value:
            return {"error": "filter_value required for filter_type='step_by_id'."}
        matched = [s for s in steps if str(s.get("id") or "").strip() == filter_value]
        return {"result": matched[0] if matched else None, "found": bool(matched)}

    elif filter_type == "steps_containing":
        if not filter_value:
            return {"error": "filter_value required for filter_type='steps_containing'."}
        fv = filter_value.lower()
        matched = [s for s in steps if fv in str(s.get("name") or "").lower()]
        return {"result": matched, "count": len(matched)}

    elif filter_type == "swimlane":
        if filter_value:
            # Case-insensitive match for the role key
            for key, val in swimlanes.items():
                if str(key).lower() == filter_value.lower():
                    # Enrich with full step objects
                    step_map = {s.get("id"): s for s in steps}
                    enriched = [step_map[sid] for sid in (val or []) if sid in step_map]
                    return {"result": {"role": key, "steps": enriched}, "count": len(enriched)}
            return {"result": None, "error": f"No swimlane found for role '{filter_value}'."}
        return {"result": swimlanes, "count": len(swimlanes)}

    elif filter_type == "metadata":
        return {"result": metadata, "count": len(metadata)}

    elif filter_type == "summary":
        return {
            "result": {
                "process_name": name,
                "role_count": len(roles),
                "roles": roles,
                "step_count": len(steps),
                "decision_count": len(decisions),
                "has_swimlanes": bool(swimlanes),
                "metadata_keys": list(metadata.keys()),
            },
            "count": 1,
        }

    else:
        valid = ["all_steps", "all_roles", "all_decisions", "steps_by_role",
                 "step_by_id", "steps_containing", "swimlane", "metadata", "summary"]
        return {"error": f"Unknown filter_type '{filter_type}'. Valid options: {valid}"}


def outline_validator(*_: Any, **__: Any) -> dict[str, Any]:
    """
    outline_validator — checks that a draft document's H2 section headings
    match an expected template exactly (by normalised keyword match).

    Unlike qa_validator which uses loose substring matching, this tool compares
    the actual heading list against an explicit expected list and reports
    extra/missing headings.

    Input:
      text: str             — the draft document
      expected: list[str]   — expected H2 heading keywords (e.g. ['purpose', 'scope', 'roles', 'procedure'])

    Returns {"passed": bool, "missing": list[str], "extra": list[str], "found": list[str]}.
    """
    text = str(__.get("text") if "text" in __ else (_[0] if _ else ""))
    expected_raw = __.get("expected") or []
    expected = [str(e).lower().strip() for e in expected_raw if str(e).strip()]
    lines = text.splitlines()
    found = [ln.lstrip("#").strip().lower() for ln in lines if ln.startswith("## ")]
    missing = [e for e in expected if not any(e in f for f in found)]
    extra = [f for f in found if not any(e in f for e in expected)]
    return {
        "passed": len(missing) == 0,
        "missing": missing,
        "extra": extra,
        "found": found,
    }


def qa_validator(*_: Any, **__: Any) -> dict[str, Any]:
    """
    qa_validator — checks that a generated document satisfies structural
    completeness requirements appropriate to its output type.

    Output-type-aware checks:
    - sop / docx: H1 title, Purpose/Scope/Roles/Procedure sections, ≥2 numbered steps
    - narrative: H1 title, 'What This Process Does' / 'Key Activities' / 'Next Actions' sections
    - raci: table header row, separator row, ≥1 data row, 5 RACI columns present
    - process_map: <mxGraphModel> present, ≥1 mxCell vertex, ≥1 edge
    - pptx: valid JSON with 'slides' key, ≥4 slides, each slide has title+layout
    - xlsx: markdown table with ≥1 data row, Activity/Owner columns present
    - pdf: H1 title, Executive Summary, Workflow sections present

    Returns ``{"passed": bool, "issues": list[str], "score": float}``.

    Scoring uses a severity-weighted rubric instead of a flat per-issue deduction:
      CRITICAL (-0.30): missing structural element without which the output is broken
                        (no H1, missing required section, no table rows, invalid XML)
      HIGH     (-0.20): missing important content that degrades usefulness
                        (missing numbered steps, missing RACI column, slide count too low)
      MEDIUM   (-0.10): style or completeness issue that reduces quality but is recoverable
                        (missing separator row, missing layout field on one slide)
    Score floors at 0.0.
    """
    text = str(__.get("text") if "text" in __ else (_[0] if _ else ""))
    output_type = str(__.get("output_type") or "").lower()

    # Severity-tagged issues: each entry is (severity_deduction, message)
    weighted_issues: list[tuple[float, str]] = []

    def crit(msg: str) -> None:
        weighted_issues.append((0.30, f"[CRITICAL] {msg}"))

    def high(msg: str) -> None:
        weighted_issues.append((0.20, f"[HIGH] {msg}"))

    def medium(msg: str) -> None:
        weighted_issues.append((0.10, f"[MEDIUM] {msg}"))

    if not text.strip():
        return {"passed": False, "issues": ["[CRITICAL] Empty content — nothing to validate."], "score": 0.0}

    lowered = text.lower()

    if output_type in ("sop", "docx"):
        lines = text.splitlines()
        if not any(ln.startswith("# ") and not ln.startswith("## ") for ln in lines):
            crit("Missing H1 title heading.")
        for sec in ["purpose", "scope", "roles", "procedure"]:
            if sec not in lowered:
                crit(f"Missing required section: '{sec}'.")
        numbered_steps = re.findall(r"^\s*\d+\.", text, flags=re.MULTILINE)
        if len(numbered_steps) == 0:
            crit("Procedure section has no numbered steps.")
        elif len(numbered_steps) < 2:
            high("Fewer than 2 numbered procedure steps found.")
        if "references" not in lowered:
            medium("Missing References section.")

    elif output_type == "narrative":
        lines = text.splitlines()
        if not any(ln.startswith("# ") and not ln.startswith("## ") for ln in lines):
            crit("Missing H1 title heading.")
        if not any(phrase in lowered for phrase in ("what this process does", "process does", "overview")):
            crit("Missing process overview section ('What This Process Does').")
        if not any(phrase in lowered for phrase in ("key activit", "workflow", "activities")):
            high("Missing key activities section.")
        if not any(phrase in lowered for phrase in ("roles and accountability", "accountability", "roles")):
            high("Missing roles and accountability section.")
        if not any(phrase in lowered for phrase in ("next action", "recommended", "action")):
            crit("Missing next actions section.")
        # Flag hedging language as medium issues
        hedges = [p for p in ("it appears", "seems to suggest", "we believe", "it seems") if p in lowered]
        for h in hedges:
            medium(f"Hedging language detected: '{h}'.")

    elif output_type == "raci":
        table_lines = [ln for ln in text.splitlines() if "|" in ln]
        if len(table_lines) < 1:
            crit("No table rows found — RACI output is empty.")
        elif len(table_lines) < 3:
            high("RACI table has fewer than 3 rows (need header + separator + ≥1 data row).")
        raci_cols = ["responsible", "accountable", "consulted", "informed"]
        for col in raci_cols:
            if col not in lowered:
                crit(f"Missing RACI column: '{col}'.")
        if table_lines:
            sep_lines = [ln for ln in table_lines if re.match(r"^\|[\s\-:]+(\|[\s\-:]+)*\|?$", ln.strip())]
            if not sep_lines:
                medium("Missing table separator row (|---|---|...).")
        # Check for 'activity' column header
        if "activity" not in lowered:
            high("Missing 'Activity' column header in RACI table.")

    elif output_type == "process_map":
        if "<mxGraphModel" not in text:
            crit("Missing <mxGraphModel> root element — output is not valid XML.")
        else:
            if 'id="0"' not in text and "id='0'" not in text:
                crit("Missing required scaffolding cell id='0' (root).")
            if 'id="1"' not in text and "id='1'" not in text:
                crit("Missing required scaffolding cell id='1' (layer).")
            if 'vertex="1"' not in text and "vertex='1'" not in text:
                crit("No vertex cells found — no step nodes in diagram.")
            if 'edge="1"' not in text and "edge='1'" not in text:
                high("No edge cells found — steps are unconnected.")

    elif output_type == "pptx":
        try:
            obj = json.loads(text) if text.strip().startswith("{") else None
            if not obj or "slides" not in obj:
                crit("Response is not a JSON object with a 'slides' key.")
            else:
                slides = obj["slides"]
                if not isinstance(slides, list):
                    crit("'slides' value is not an array.")
                elif len(slides) < 4:
                    high(f"Only {len(slides)} slide(s); minimum 4 required for a complete deck.")
                else:
                    for i, slide in enumerate(slides):
                        if not isinstance(slide, dict):
                            high(f"Slide {i+1} is not an object.")
                            continue
                        if not slide.get("title"):
                            crit(f"Slide {i+1} missing required 'title' field.")
                        # Accept either new slide_type or legacy layout field
                        if not slide.get("slide_type") and not slide.get("layout"):
                            medium(f"Slide {i+1} missing 'slide_type' field.")
                        # Content check covers all current slide_type content fields
                        has_content = bool(
                            slide.get("bullets") or slide.get("table") or slide.get("chart") or
                            slide.get("stat_cards") or slide.get("column_cards") or slide.get("stack_layers")
                        )
                        # Slides that legitimately carry no content blocks
                        _no_content_types = ("title_only", "blank", "title", "section_divider")
                        slide_type_val = slide.get("slide_type") or slide.get("layout") or ""
                        if not has_content and slide_type_val not in _no_content_types:
                            medium(f"Slide {i+1} has no content (bullets, table, chart, stat_cards, column_cards, or stack_layers).")
        except Exception:
            crit("PPTX response could not be parsed as JSON.")

    elif output_type == "xlsx":
        table_lines = [ln for ln in text.splitlines() if ln.strip().startswith("|")]
        if len(table_lines) < 1:
            crit("No table rows found — XLSX output is empty.")
        elif len(table_lines) < 3:
            high("XLSX table has fewer than 3 rows (need header + separator + ≥1 data row).")
        if "activity" not in lowered:
            crit("Missing 'Activity' column header.")
        if "owner" not in lowered:
            high("Missing 'Owner' column header.")
        # Check for blank cells
        data_lines = [ln for ln in table_lines[2:] if not re.match(r"^\|[\s\-:]+(\|[\s\-:]+)*\|?$", ln.strip())]
        blank_count = sum(1 for ln in data_lines for cell in ln.split("|")[1:-1] if not cell.strip())
        if blank_count > 0:
            medium(f"{blank_count} blank cell(s) detected — use '—' for empty values.")

    elif output_type == "pdf":
        lines = text.splitlines()
        if not any(ln.startswith("# ") and not ln.startswith("## ") for ln in lines):
            crit("Missing H1 title heading.")
        if "executive summary" not in lowered:
            crit("Missing 'Executive Summary' section.")
        if not any(phrase in lowered for phrase in ("workflow", "procedure", "process")):
            high("Missing workflow overview section.")
        if not any(phrase in lowered for phrase in ("next action", "next step", "recommendation")):
            high("Missing next actions section.")

    else:
        lines = text.splitlines()
        if not any(ln.startswith("#") for ln in lines):
            high("No headings found — document lacks structure.")

    issues = [msg for _, msg in weighted_issues]
    total_deduction = sum(d for d, _ in weighted_issues)
    score = max(0.0, round(1.0 - total_deduction, 2))
    return {"passed": len(issues) == 0, "issues": issues, "score": score}


def style_enforcer(*_: Any, **__: Any) -> dict[str, Any]:
    """
    style_enforcer — checks brand and style consistency in text content.

    Evaluates:
    - Use of approved heading hierarchy (# / ## / ###)
    - Absence of promotional language banned by brand guidelines
    - Sentence length (readability)
    - Consistent tone markers (imperative for SOPs, narrative for reports)

    Returns ``{"passed": bool, "issues": list[str], "suggestions": list[str]}``.
    """
    text = str(__.get("text") if "text" in __ else (_[0] if _ else ""))
    output_type = str(__.get("output_type") or "").lower()

    issues: list[str] = []
    suggestions: list[str] = []

    if not text.strip():
        return {"passed": False, "issues": ["Empty content."], "suggestions": []}

    # Banned promotional phrases (brand_guidelines_v1)
    banned_phrases = (
        "best-in-class", "guaranteed", "revolutionary", "unprecedented",
        "cutting-edge", "world-class", "industry-leading",
    )
    for phrase in banned_phrases:
        if phrase in text.lower():
            issues.append(f"Banned promotional phrase: '{phrase}'")

    # Heading hierarchy check
    lines = text.splitlines()
    has_h1 = any(ln.startswith("# ") and not ln.startswith("## ") for ln in lines)
    has_headings = any(ln.startswith("#") for ln in lines)
    if not has_headings and len(text) > 400:
        suggestions.append("Consider adding markdown headings to structure the content.")

    # Sentence length (readability signal)
    long_sentences = [
        ln.strip() for ln in re.split(r"[.!?]", text)
        if len(ln.split()) > 50
    ]
    if long_sentences:
        issues.append(f"{len(long_sentences)} overly long sentence(s) detected — target ≤50 words per sentence.")

    # SOP-specific: imperative tone check (steps should start with verbs)
    if output_type == "sop":
        numbered = re.findall(r"^\s*\d+\.\s+(\w+)", text, flags=re.MULTILINE)
        non_imperative = [w for w in numbered if w.endswith("ing") or w.lower() in ("the", "a", "an")]
        if non_imperative:
            suggestions.append(
                f"SOP steps should use imperative verbs. Check: {', '.join(non_imperative[:3])}"
            )

    _ = has_h1  # suppress unused warning
    return {
        "passed": len(issues) == 0,
        "issues": issues,
        "suggestions": suggestions,
    }


TOOL_REGISTRY: dict[str, ToolHandler] = {
    "retrieve_context": retrieve_context,
    "memory_lookup": memory_lookup,
    "memory_items": memory_items,
    "web_search": web_search,
    "web_capture": web_capture,
    "search_leading_practices": search_leading_practices,
    "search_wiki": search_wiki,
    "validate_references": validate_references,
    "check_brand_compliance": check_brand_compliance,
    "drawio_process_model_to_xml": drawio_process_model_to_xml,
    "qa_validator": qa_validator,
    "style_enforcer": style_enforcer,
    # Structural validators — implementations for tools declared in skill cards
    "document_builder": document_builder,
    "diagram_builder": diagram_builder,
    "table_builder": table_builder,
    # Content integrity and formatting utilities
    "cross_reference_checker": cross_reference_checker,
    "format_table": format_table,
    "outline_validator": outline_validator,
    # Draft storage — multi-round revision workflow
    "save_draft": save_draft,
    "load_draft": load_draft,
    # Structured ProcessModel access
    "process_model_query": process_model_query,
    # Swarm task board + messaging (when SWARM_ORCHESTRATION_ENABLED)
    "swarm_list_tasks": swarm_list_tasks,
    "swarm_create_task": swarm_create_task,
    "swarm_update_task": swarm_update_task,
    "swarm_list_messages": swarm_list_messages,
    "swarm_send_message": swarm_send_message,
    "swarm_broadcast": swarm_broadcast,
}

# Anthropic tool definitions: name -> description + JSON Schema for input
_TOOL_METADATA: dict[str, dict[str, Any]] = {
    "retrieve_context": {
        "description": "Retrieve relevant snippets from parsed project documents using a lexical query.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query for document chunks"},
            },
            "required": ["query"],
        },
    },
    "memory_lookup": {
        "description": "Alias for retrieve_context: search parsed **document** chunks (not Memory page items).",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
            },
            "required": ["query"],
        },
    },
    "memory_items": {
        "description": "List structured MemoryItem entries for this project (preferences, facts, constraints).",
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Max items to return (1–40, default 25)",
                },
            },
        },
    },
    "web_search": {
        "description": "Search the public web for current facts (uses configured search backend).",
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "Web search query"}},
            "required": ["query"],
        },
    },
    "web_capture": {
        "description": (
            "Fetch a single public HTTPS URL and return title + readable text (SSRF-safe). "
            "Rejects non-HTTPS schemes, private/loopback/metadata IPs, and oversized responses. "
            "Use after web_search when you need the actual content of a result."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "Public HTTPS URL to capture"},
                "max_chars": {
                    "type": "integer",
                    "description": "Upper bound on returned text length (default 8000, max 32000)",
                },
                "max_bytes": {
                    "type": "integer",
                    "description": "Upper bound on response body bytes (falls back to server default)",
                },
                "timeout": {
                    "type": "number",
                    "description": "Request timeout in seconds (falls back to server default)",
                },
            },
            "required": ["url"],
        },
    },
    "search_leading_practices": {
        "description": "Search the leading-practices library for relevant guidance, templates, and best-practice patterns.",
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "Topic or question to look up"}},
            "required": ["query"],
        },
    },
    "search_wiki": {
        "description": (
            "Search the project wiki for relevant pages. Use when the user asks about process details, "
            "roles, domain knowledge, or any topic that might be documented in the project wiki."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "max_results": {
                    "type": "integer",
                    "description": "Maximum wiki pages to return (default 8, max 20)",
                },
            },
            "required": ["query"],
        },
    },
    "validate_references": {
        "description": "Check draft text for citation markers and obvious reference issues.",
        "input_schema": {
            "type": "object",
            "properties": {"text": {"type": "string", "description": "Draft content to validate"}},
            "required": ["text"],
        },
    },
    "check_brand_compliance": {
        "description": "Check text for promotional or non-compliant phrasing.",
        "input_schema": {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
    },
    "drawio_process_model_to_xml": {
        "description": "Convert a ProcessModel JSON object to diagrams.net (draw.io) XML.",
        "input_schema": {
            "type": "object",
            "properties": {"process_model": _JSON_OBJECT_SCHEMA},
            "required": ["process_model"],
        },
    },
    "qa_validator": {
        "description": (
            "Validate structural completeness of a generated document. "
            "Checks for required sections, numbered steps, and other quality signals. "
            "Returns passed (bool), issues (list), and score (0.0–1.0)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Generated document content to validate"},
                "output_type": {
                    "type": "string",
                    "description": "Type of document: sop, narrative, docx, raci, etc.",
                },
            },
            "required": ["text"],
        },
    },
    "style_enforcer": {
        "description": (
            "Check text for brand and style compliance: banned promotional phrases, "
            "heading hierarchy, sentence length, and tone conventions. "
            "Returns passed (bool), issues (list), and suggestions (list)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Content to check for style compliance"},
                "output_type": {
                    "type": "string",
                    "description": "Document type (sop, narrative, pptx, etc.) for tone checks",
                },
            },
            "required": ["text"],
        },
    },
    "document_builder": {
        "description": (
            "Validate a Markdown document intended for DOCX export. "
            "Checks for H1 title, required H2 sections (Purpose, Scope, Roles, Procedure), "
            "and ≥2 numbered steps. Returns passed (bool) and issues (list). "
            "Call this after drafting to confirm the document is structurally complete before finalising."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "The drafted Markdown document content"},
            },
            "required": ["text"],
        },
    },
    "diagram_builder": {
        "description": (
            "Validate mxGraphModel XML for diagrams.net (draw.io) export. "
            "Checks for required scaffolding cells (id=0, id=1), ≥1 vertex cell (step node), "
            "and ≥1 edge cell (connection). Returns passed (bool), issues (list), "
            "vertex_count (int), and edge_count (int). "
            "Call this after generating XML to confirm it is structurally valid before finalising."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "xml": {"type": "string", "description": "The generated mxGraphModel XML content"},
            },
            "required": ["xml"],
        },
    },
    "table_builder": {
        "description": (
            "Validate a GitHub-flavored Markdown table. "
            "Checks for header row, separator row, consistent column counts, "
            "and absence of blank cells (each must contain text or '—'). "
            "Returns passed (bool), issues (list), row_count (int), and column_count (int). "
            "Call this after building a RACI, XLSX, or any tabular output to confirm it is well-formed."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "The Markdown table content"},
            },
            "required": ["text"],
        },
    },
    "cross_reference_checker": {
        "description": (
            "Verify that role names and step names in a generated document match the ProcessModel source of truth. "
            "Detects hallucinated roles (names not in ProcessModel.roles) and fabricated step names "
            "(activities not derived from ProcessModel.steps). "
            "Returns passed (bool), unmatched_roles (list), and unmatched_steps (list). "
            "Call this on final drafts before returning, especially for RACI and SOP outputs."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "The generated document content to check"},
                "process_model": {
                    "type": "object",
                    "description": "The ProcessModel JSON object (source of truth for roles and steps)",
                    "additionalProperties": True,
                },
            },
            "required": ["text"],
        },
    },
    "format_table": {
        "description": (
            "Convert ProcessModel step data into a clean Markdown table with specified columns. "
            "Available columns: Activity, Owner, Inputs, Outputs, Tools, Duration, Notes. "
            "Returns markdown (str) — the formatted table ready to embed in a document. "
            "Use this instead of building tables inline to avoid formatting errors."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "process_model": {
                    "type": "object",
                    "description": "The ProcessModel JSON object",
                    "additionalProperties": True,
                },
                "columns": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Ordered list of column names. "
                        "Valid values: Activity, Owner, Inputs, Outputs, Tools, Duration, Notes"
                    ),
                },
            },
            "required": ["process_model"],
        },
    },
    "outline_validator": {
        "description": (
            "Check that a draft document's H2 section headings match an expected template. "
            "More precise than qa_validator — compares actual headings against an explicit expected list "
            "and reports both missing and unexpected extra sections. "
            "Returns passed (bool), missing (list), extra (list), and found (list). "
            "Use before finalising any structured document to confirm the outline is correct."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "The draft document content"},
                "expected": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of expected H2 section keywords (lowercase, e.g. ['purpose', 'scope', 'procedure'])",
                },
            },
            "required": ["text", "expected"],
        },
    },
    "save_draft": {
        "description": (
            "Save an intermediate draft to the project workspace for retrieval in a later round. "
            "Use this to persist work-in-progress before a validation or quality gate round, "
            "so you can load and revise it rather than regenerating from scratch. "
            "Call with key='v1' after first draft, 'v2' after revision, etc. "
            "Returns saved (bool), path (str), and bytes (int)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "The draft content to persist"},
                "key": {
                    "type": "string",
                    "description": "Identifier for this draft version (e.g. 'v1', 'initial', 'revised'). "
                                   "Use consistent keys across save/load pairs.",
                },
                "agent_id": {
                    "type": "string",
                    "description": "Agent name for namespacing (e.g. 'sop', 'raci'). Defaults to 'agent'.",
                },
            },
            "required": ["content"],
        },
    },
    "load_draft": {
        "description": (
            "Retrieve a previously saved draft from the project workspace. "
            "Use after save_draft to access an earlier version for revision or comparison. "
            "Returns found (bool) and content (str) if the draft exists."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "key": {
                    "type": "string",
                    "description": "The key used when save_draft was called (e.g. 'v1', 'initial').",
                },
                "agent_id": {
                    "type": "string",
                    "description": "Agent name used in the corresponding save_draft call.",
                },
            },
            "required": ["key"],
        },
    },
    "process_model_query": {
        "description": (
            "Structured query interface for ProcessModel data. "
            "Use this instead of parsing the raw ProcessModel JSON to fetch specific subsets. "
            "filter_type options: "
            "'all_steps' (all steps), "
            "'all_roles' (role list), "
            "'all_decisions' (decision branches), "
            "'steps_by_role' (steps where role matches filter_value), "
            "'step_by_id' (single step by id, e.g. 's3'), "
            "'steps_containing' (steps whose name contains filter_value), "
            "'swimlane' (swimlane for a role, or all swimlanes if filter_value omitted), "
            "'metadata' (process metadata dict), "
            "'summary' (name + counts). "
            "Returns result (object/list/string) and count (int)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "filter_type": {
                    "type": "string",
                    "enum": [
                        "all_steps", "all_roles", "all_decisions",
                        "steps_by_role", "step_by_id", "steps_containing",
                        "swimlane", "metadata", "summary",
                    ],
                    "description": "The type of query to perform",
                },
                "filter_value": {
                    "type": "string",
                    "description": "The value to filter by (required for steps_by_role, step_by_id, steps_containing, swimlane)",
                },
            },
            "required": ["filter_type"],
        },
    },
    "swarm_list_tasks": {
        "description": "List RunTask rows for this run (swarm board). Optional status/phase filter.",
        "input_schema": {
            "type": "object",
            "properties": {
                "status": {"type": "string", "description": "Filter by status (e.g. queued, completed)"},
                "phase": {"type": "string", "description": "Filter by phase"},
            },
        },
    },
    "swarm_create_task": {
        "description": "Create a queued task on the swarm board with optional dependencies (DAG validated).",
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "description": {"type": "string"},
                "depends_on": {"type": "array", "items": {"type": "string"}},
                "phase": {"type": "string", "description": "Default act; use custom for coordinator-executed tasks"},
                "assigned_teammate_id": {"type": "string"},
                "priority": {"type": "integer"},
                "task_id": {"type": "string", "description": "Optional stable id; auto-generated if omitted"},
            },
            "required": ["title"],
        },
    },
    "swarm_update_task": {
        "description": "Patch task status, blocked_reason, assignee, or priority.",
        "input_schema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string"},
                "status": {"type": "string"},
                "blocked_reason": {"type": "string"},
                "assigned_teammate_id": {"type": "string"},
                "priority": {"type": "integer"},
            },
            "required": ["task_id"],
        },
    },
    "swarm_list_messages": {
        "description": "List recent swarm team messages (newest last in items).",
        "input_schema": {
            "type": "object",
            "properties": {"limit": {"type": "integer", "description": "Max messages (default 50, max 200)"}},
        },
    },
    "swarm_send_message": {
        "description": "Send a direct or team-visible message on the swarm board.",
        "input_schema": {
            "type": "object",
            "properties": {
                "from_teammate": {"type": "string"},
                "body": {"type": "string"},
                "to_teammate": {"type": "string", "description": "Omit for broadcast-style visibility in mailbox"},
                "correlation_id": {"type": "string"},
            },
            "required": ["from_teammate", "body"],
        },
    },
    "swarm_broadcast": {
        "description": "Broadcast a message to all teammates (same as send without to_teammate).",
        "input_schema": {
            "type": "object",
            "properties": {
                "from_teammate": {"type": "string"},
                "body": {"type": "string"},
            },
            "required": ["from_teammate", "body"],
        },
    },
}

_DEFAULT_TOOLS_BY_OUTPUT: dict[str, list[str]] = {
    # process_map: context + all search tools + process model query + deterministic XML builder + validator
    "process_map": [
        "retrieve_context",
        "search_wiki",
        "search_leading_practices",
        "web_search",
        "process_model_query",
        "drawio_process_model_to_xml",
        "diagram_builder",
        "qa_validator",
    ],
    # docx: context + all search tools + process model query + draft revision + structural validators
    "docx": [
        "retrieve_context",
        "search_wiki",
        "search_leading_practices",
        "web_search",
        "process_model_query",
        "save_draft",
        "load_draft",
        "cross_reference_checker",
        "document_builder",
        "outline_validator",
        "qa_validator",
        "style_enforcer",
    ],
    # pptx: context + all search tools + process model query + format_table + draft revision + validator
    "pptx": [
        "retrieve_context",
        "search_wiki",
        "search_leading_practices",
        "web_search",
        "process_model_query",
        "format_table",
        "save_draft",
        "load_draft",
        "qa_validator",
        "style_enforcer",
    ],
    # xlsx: context + all search tools + process model query + format_table + table validator
    "xlsx": [
        "retrieve_context",
        "search_wiki",
        "search_leading_practices",
        "web_search",
        "process_model_query",
        "format_table",
        "table_builder",
        "qa_validator",
    ],
    # pdf: context + all search tools + process model query + draft revision + cross-reference + structural check
    "pdf": [
        "retrieve_context",
        "search_wiki",
        "search_leading_practices",
        "web_search",
        "process_model_query",
        "save_draft",
        "load_draft",
        "cross_reference_checker",
        "qa_validator",
        "style_enforcer",
    ],
}


def get_tool(name: str) -> ToolHandler:
    try:
        return TOOL_REGISTRY[name]
    except KeyError as exc:
        raise ValueError(f"Unknown tool: {name}") from exc


def list_tools() -> list[str]:
    return sorted(TOOL_REGISTRY.keys())


def tool_to_anthropic_schema(name: str) -> dict[str, Any]:
    """Return a single Anthropic Messages API tool definition (name, description, input_schema)."""
    meta = _TOOL_METADATA.get(name)
    if not meta:
        raise ValueError(f"No tool schema for {name!r}")
    if name not in TOOL_REGISTRY:
        raise ValueError(f"Unknown tool: {name!r}")
    return {
        "name": name,
        "description": str(meta.get("description") or name),
        "input_schema": meta.get("input_schema") or {"type": "object", "properties": {}},
    }


def anthropic_tool_definitions(names: list[str]) -> list[dict[str, Any]]:
    """Build tool list for the Messages API, skipping unknown names with a log line."""
    out: list[dict[str, Any]] = []
    for n in names:
        n = str(n).strip()
        if not n:
            continue
        try:
            out.append(tool_to_anthropic_schema(n))
        except ValueError:
            _LOG.warning("tool_registry: skipping unknown or unschemaed tool %r", n)
    return out


def tool_names_for_skill(skill_card: dict[str, Any] | None) -> list[str]:
    if not isinstance(skill_card, dict):
        return []
    raw = skill_card.get("tools")
    if not isinstance(raw, list):
        return []
    names: list[str] = []
    for x in raw:
        s = str(x).strip()
        if s and s in TOOL_REGISTRY and s not in names:
            names.append(s)
        elif s and s not in TOOL_REGISTRY:
            _LOG.warning("tool_registry: skill references unknown tool %r", s)
    return names


def default_tools_for_output_type(output_type: str) -> list[str]:
    return list(
        _DEFAULT_TOOLS_BY_OUTPUT.get(output_type, ["retrieve_context", "validate_references", "memory_items"])
    )


def _try_mcp_tool_call(name: str, tool_input: dict[str, Any]) -> Any | None:
    """
    Try to resolve and call a tool via MCP servers.
    Returns result if found and callable, None otherwise.
    """
    try:
        from app.services.mcp.bridge import try_mcp_tool_call
        from app.services.mcp.registry import get_mcp_registry

        registry = get_mcp_registry()

        # Iterate through all running servers, try each one
        for server_id in registry.servers:
            result = try_mcp_tool_call(server_id, name, tool_input)
            if result is not None:
                _LOG.info(
                    f"tool_registry: resolved tool {name!r} from MCP server {server_id!r}"
                )
                return result

        return None
    except Exception as e:
        _LOG.debug(f"tool_registry: MCP tool call failed: {e}")
        return None


def resolve_tool_call(name: str, tool_input: dict[str, Any], context: dict[str, Any]) -> Any:
    """
    Execute a registry tool with model-provided input merged with server context
    (e.g. project_id, user_id, process_model). Returns JSON-serializable data.

    Resolution order:
    1. Native tool registry (fastest, deterministic)
    2. MCP servers (if configured and running)
    3. Error if not found
    """
    # Try native registry first
    if name in TOOL_REGISTRY:
        handler = TOOL_REGISTRY[name]
        merged: dict[str, Any] = dict(tool_input) if isinstance(tool_input, dict) else {}
        # Inject server-side context values — model input takes precedence (setdefault)
        for ctx_key in ("project_id", "user_id"):
            if context.get(ctx_key) is not None:
                merged.setdefault(ctx_key, context[ctx_key])
        if context.get("process_model") is not None and "process_model" not in merged:
            merged.setdefault("process_model", context["process_model"])
        # Inject run_id and agent_id for draft storage and audit trail
        if context.get("run_id") is not None:
            merged.setdefault("run_id", context["run_id"])
        if context.get("agent_id") is not None:
            merged.setdefault("agent_id", context["agent_id"])
        if context.get("swarm_teammate_id") is not None:
            merged.setdefault("swarm_teammate_id", context["swarm_teammate_id"])
        return handler(**merged)

    # Fall back to MCP servers
    mcp_result = _try_mcp_tool_call(name, tool_input)
    if mcp_result is not None:
        return mcp_result

    # Not found anywhere
    raise ValueError(f"Unknown tool: {name!r} (not in native registry or MCP servers)")


def tool_result_to_text(result: Any, *, max_chars: int = 24000) -> str:
    if isinstance(result, str):
        text = result
    else:
        try:
            text = json.dumps(result, ensure_ascii=False, default=str)
        except Exception:
            text = str(result)
    if len(text) > max_chars:
        return text[: max_chars - 1] + "…"
    return text

