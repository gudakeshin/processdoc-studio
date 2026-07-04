"""Pure discovery slot extraction/merge helpers for the conversation router.

Extracted verbatim from conversation.py; re-imported there so the
monkeypatch contract on app.api.projects.conversation.<name> still holds.
"""

import logging
import re

from app.services.retrieval import TieredContextEngine

_LOG = logging.getLogger(__name__)


def _normalize_discovery(raw: object) -> dict:
    if not isinstance(raw, dict):
        return {}
    out: dict[str, object] = {}
    client = raw.get("client")
    if isinstance(client, str) and client.strip():
        client = {"name": client.strip()}
    if isinstance(client, dict):
        name = str(client.get("name") or "").strip()
        industry = str(client.get("industry") or "").strip()
        if name or industry:
            out["client"] = {"name": name, "industry": industry}
    outcome = raw.get("outcome")
    if isinstance(outcome, str) and outcome.strip():
        outcome = {"primary": outcome.strip()}
    if isinstance(outcome, dict):
        primary = str(outcome.get("primary") or "").strip()
        decision = str(outcome.get("decision") or "").strip()
        if primary or decision:
            out["outcome"] = {"primary": primary, "decision": decision}
    themes = raw.get("win_themes")
    if isinstance(themes, str) and themes.strip():
        themes = [t.strip() for t in re.split(r"[,;]|\band\b", themes) if t.strip()]
    if isinstance(themes, list):
        vals = [str(x).strip() for x in themes if str(x).strip()]
        if vals:
            out["win_themes"] = vals[:3]
    audience = str(raw.get("audience") or "").strip().lower()
    if audience:
        out["audience"] = audience
    narrative_arc = str(raw.get("narrative_arc") or "").strip().lower()
    if narrative_arc:
        out["narrative_arc"] = narrative_arc
    tone = str(raw.get("tone") or "").strip().lower()
    if tone:
        out["tone"] = tone
    length_budget = raw.get("length_budget")
    if isinstance(length_budget, dict):
        lb: dict[str, int] = {}
        try:
            pptx = int(length_budget.get("pptx")) if length_budget.get("pptx") is not None else None
            if pptx and 4 <= pptx <= 30:
                lb["pptx"] = pptx
        except Exception as exc:
            _LOG.warning("%s: suppressed error: %s", '_normalize_discovery', exc)
        try:
            docx_pages = int(length_budget.get("docx_pages")) if length_budget.get("docx_pages") is not None else None
            if docx_pages and 2 <= docx_pages <= 120:
                lb["docx_pages"] = docx_pages
        except Exception as exc:
            _LOG.warning("%s: suppressed error: %s", '_normalize_discovery', exc)
        if lb:
            out["length_budget"] = lb
    edited_by_user = raw.get("edited_by_user")
    if isinstance(edited_by_user, bool):
        out["edited_by_user"] = edited_by_user
    return out


def _merge_discovery(base: object, incoming: object) -> dict:
    merged = _normalize_discovery(base)
    extra = _normalize_discovery(incoming)
    if not extra:
        return merged
    for key in ("client", "outcome", "length_budget"):
        if key in extra:
            b = merged.get(key) if isinstance(merged.get(key), dict) else {}
            i = extra.get(key) if isinstance(extra.get(key), dict) else {}
            # Keep prior non-empty values when a new extraction only provides
            # partial fields (e.g. outcome.decision without outcome.primary).
            next_obj = dict(b)
            for fk, fv in i.items():
                if isinstance(fv, str):
                    if fv.strip():
                        next_obj[fk] = fv
                elif fv is not None:
                    next_obj[fk] = fv
            merged[key] = next_obj
    for key in ("audience", "narrative_arc", "tone", "edited_by_user"):
        if key in extra:
            merged[key] = extra[key]
    if "win_themes" in extra:
        existing = merged.get("win_themes")
        cur = existing if isinstance(existing, list) else []
        nxt = extra.get("win_themes") if isinstance(extra.get("win_themes"), list) else []
        merged["win_themes"] = (cur + [x for x in nxt if x not in cur])[:3]
    return merged


def _has_sufficient_discovery(discovery: object) -> bool:
    data = _normalize_discovery(discovery)
    client = data.get("client") if isinstance(data.get("client"), dict) else {}
    outcome = data.get("outcome") if isinstance(data.get("outcome"), dict) else {}
    themes = data.get("win_themes") if isinstance(data.get("win_themes"), list) else []
    has_outcome = bool(str(outcome.get("primary") or "").strip() or str(outcome.get("decision") or "").strip())
    return bool(str(client.get("name") or "").strip() and has_outcome and themes)


def _required_discovery_missing_slots(discovery: object) -> list[str]:
    """Compute required discovery gaps from canonical merged slots."""
    data = _normalize_discovery(discovery)
    client = data.get("client") if isinstance(data.get("client"), dict) else {}
    outcome = data.get("outcome") if isinstance(data.get("outcome"), dict) else {}
    themes = data.get("win_themes") if isinstance(data.get("win_themes"), list) else []
    missing: list[str] = []
    if not str(client.get("name") or "").strip():
        missing.append("client")
    if not (str(outcome.get("primary") or "").strip() or str(outcome.get("decision") or "").strip()):
        missing.append("outcome")
    if not [str(x).strip() for x in themes if str(x).strip()]:
        missing.append("win_themes")
    return missing


def _extract_entity_tokens(text: str) -> list[str]:
    candidates = re.findall(r"\b[A-Z][A-Za-z0-9&.\-]{2,}\b", str(text or ""))
    out: list[str] = []
    seen: set[str] = set()
    for token in candidates:
        key = token.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(token)
        if len(out) >= 8:
            break
    return out


def _top_parsed_doc_chunks_for_query(project_id: str, query_text: str, max_chunks: int = 2) -> list[dict]:
    try:
        engine = TieredContextEngine()
        chunks = engine._load_all_parsed_chunks(project_id)  # noqa: SLF001
        if not chunks:
            return []
        scores = engine._bm25_scores(chunks, query_text)  # noqa: SLF001
        ranked = [chunks[i] for i, score in sorted(enumerate(scores), key=lambda x: x[1], reverse=True) if score > 0]
        return ranked[:max_chunks]
    except Exception as exc:
        _LOG.warning("wiki slot extractor: parsed doc retrieval failed for project %s: %s", project_id, exc)
        return []


def _extract_discovery_answers_from_wiki(
    *,
    project_id: str,
    user_message: str,
    prior_messages: list[dict],
) -> tuple[dict[str, object], list[str]]:
    from app.services.claude import claude_generate_json
    from app.services.wiki_query import _get_wiki_index, _search_wiki_pages

    seed_query = "client name industry primary audience outcome decision win themes proof points"
    entity_tokens = _extract_entity_tokens(user_message)
    query = f"{seed_query} {' '.join(entity_tokens)}".strip()
    wiki_refs: list[str] = []
    wiki_pages: list[dict] = []
    try:
        index = _get_wiki_index("project", project_id)
        wiki_pages = _search_wiki_pages(query, index or {"pages": []}, "project", project_id)[:6]
    except Exception:
        wiki_pages = []
    wiki_excerpt: list[str] = []
    for page in wiki_pages:
        if not isinstance(page, dict):
            continue
        title = str(page.get("title") or page.get("page_id") or "").strip()
        if title:
            wiki_refs.append(title)
        body = str(page.get("content") or "").strip()
        if title and body:
            wiki_excerpt.append(f"[Wiki: {title}]\n{body[:700]}")
    doc_chunks = _top_parsed_doc_chunks_for_query(project_id, query, max_chunks=2)
    doc_excerpt = []
    for chunk in doc_chunks:
        if not isinstance(chunk, dict):
            continue
        source = str(chunk.get("source") or chunk.get("title") or "parsed_doc").strip()
        text = str(chunk.get("text") or "").strip()
        if text:
            doc_excerpt.append(f"[Doc: {source}]\n{text[:700]}")
    if not wiki_excerpt and not doc_excerpt:
        return {}, []

    prior_context = "\n".join(
        f"{m.get('role', 'user')}: {str(m.get('content') or '').strip()}"
        for m in prior_messages[-6:]
        if str(m.get("content") or "").strip()
    )
    evidence = "\n\n".join(wiki_excerpt + doc_excerpt)[:5000]
    try:
        payload = claude_generate_json(
            system=(
                "Extract proposal discovery details from evidence snippets. "
                "Return JSON only with keys: "
                "client{name,industry}, outcome{primary,decision}, win_themes[array max 3], audience, source_refs[array]. "
                "Use only explicit evidence. Leave unknown fields empty or omitted."
            ),
            user=(
                f"Recent chat context:\n{prior_context}\n\n"
                f"Latest user message:\n{user_message}\n\n"
                f"Evidence:\n{evidence}"
            ),
            temperature=0.1,
            max_tokens=500,
        )
    except Exception:
        return {}, wiki_refs[:6]
    normalized = _normalize_discovery(payload)
    source_refs_raw = payload.get("source_refs") if isinstance(payload, dict) else []
    source_refs = []
    if isinstance(source_refs_raw, list):
        for item in source_refs_raw:
            text = str(item or "").strip()
            if text and text in wiki_refs and text not in source_refs:
                source_refs.append(text)
    return normalized, (source_refs or wiki_refs[:6])


def _extract_discovery_answers(user_message: str, prior_messages: list[dict]) -> dict:
    from app.services.claude import claude_generate_json

    context = "\n".join(
        f"{m.get('role', 'user')}: {str(m.get('content') or '').strip()}"
        for m in prior_messages[-15:]
        if str(m.get("content") or "").strip()
    )
    try:
        payload = claude_generate_json(
            system=(
                "Extract proposal discovery details from a user's response. "
                "Return JSON with this exact structure (omit fields with no evidence): "
                '{"client": {"name": "...", "industry": "..."}, '
                '"outcome": {"primary": "...", "decision": "..."}, '
                '"win_themes": ["...", "..."], "audience": "..."}. '
                "client.name = company name. outcome.primary = the problem/goal being solved. "
                "win_themes = key differentiators or proof points. Never return empty strings."
            ),
            user=f"Recent chat context:\n{context}\n\nLatest user response:\n{user_message}",
            temperature=0.1,
            max_tokens=300,
        )
        return _normalize_discovery(payload)
    except Exception:
        return {}


def _extract_discovery_answers_fast(user_message: str) -> dict:
    """Best-effort deterministic extraction for common discovery answer phrasings."""
    text = str(user_message or "").strip()
    lowered = text.lower()
    out: dict[str, object] = {}

    client_match = re.search(r"\bclient\s+is\s+([^\-.,\n]+)", text, re.IGNORECASE)
    if client_match:
        client_name = client_match.group(1).strip()
        if client_name:
            out["client"] = {"name": client_name}

    industry_match = re.search(r"\bindustry\s*(?:is|:)\s*([^.\n]+)", text, re.IGNORECASE)
    if industry_match:
        industry = industry_match.group(1).strip()
        cur = out.get("client") if isinstance(out.get("client"), dict) else {}
        out["client"] = {**cur, "industry": industry}

    audience_match = re.search(
        r"\b(?:primary\s+audience|audience)\s*(?:is|:)\s*([^.\n]+)",
        text,
        re.IGNORECASE,
    )
    if audience_match:
        out["audience"] = audience_match.group(1).strip().lower()

    theme_matches = re.findall(r"\b(?:key\s+)?win\s+theme(?:s)?\s*(?:is|are|:)\s*([^.\n]+)", text, re.IGNORECASE)
    if theme_matches:
        themes: list[str] = []
        for m in theme_matches:
            parts = [p.strip(" -") for p in re.split(r",| and ", m) if p.strip()]
            themes.extend(parts)
        if themes:
            out["win_themes"] = themes[:3]

    outcome_match = re.search(
        r"\btransformation\s+problem\s*(?:is|:)\s*([^.\n]+)",
        text,
        re.IGNORECASE,
    )
    if outcome_match:
        out["outcome"] = {"primary": outcome_match.group(1).strip()}
    else:
        # Common natural phrasing in chat: "proposal should help them decide X"
        # or "should help decide X". Capture that as the decision and derive a
        # primary outcome so we don't re-ask the same slot every turn.
        decision_match = re.search(
            r"\b(?:proposal|document|deck)?\s*should\s+help(?:\s+\w+){0,3}\s+decide\s*(?:on|whether|to)?\s*([^.\n]+)",
            text,
            re.IGNORECASE,
        )
        if decision_match:
            decision = decision_match.group(1).strip(" :,-")
            if decision:
                out["outcome"] = {
                    "primary": f"Support decision-making on {decision}",
                    "decision": decision,
                }
    if "outcome" not in out:
        decision_is_match = re.search(
            r"\bdecision\s*(?:is|:)\s*([^.\n]+)",
            text,
            re.IGNORECASE,
        )
        if decision_is_match:
            decision = decision_is_match.group(1).strip(" :,-")
            if decision:
                out["outcome"] = {
                    "primary": f"Support decision-making on {decision}",
                    "decision": decision,
                }
    if "outcome" not in out and "driving transformation" in lowered:
        out["outcome"] = {"primary": "Drive transformation across processes"}

    return _normalize_discovery(out)
