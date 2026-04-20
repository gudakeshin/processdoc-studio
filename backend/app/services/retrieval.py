from __future__ import annotations

import json
import math
import re
import time
from dataclasses import dataclass
from pathlib import Path

from app.services.storage import workspace_path


@dataclass
class ContextBundle:
    text: str
    char_budget: int = 32000
    metadata: dict[str, object] | None = None


_TOKEN_RE = re.compile(r"[^a-zA-Z0-9]+")


def _tokenize(s: str) -> list[str]:
    s = (s or "").lower()
    parts = [p for p in _TOKEN_RE.split(s) if p]
    return parts


class TieredContextEngine:
    """
    Tiered context assembly:
    - Tier 0: CONTEXT.md (+ optional style/context provided by caller)
    - Tier 1: LP snippets (currently passed in; OneDrive integration is added later)
    - Tier 2: source_docs chunks ranked by BM25, merged with MMR-style deduplication
    """

    def __init__(self) -> None:
        self.k1 = 1.5
        self.b = 0.75
        self._parsed_cache: dict[str, tuple[float, list[str]]] = {}
        self._wiki_cache: dict[str, tuple[float, list[str]]] = {}

    def _load_all_parsed_chunks(self, project_id: str | None) -> list[str]:
        if not project_id:
            return []
        parsed_dir = workspace_path(project_id) / "parsed_docs"
        if not parsed_dir.exists():
            return []
        cache_key = str(parsed_dir)
        latest_mtime = 0.0
        parsed_files = list(parsed_dir.glob("*.json"))
        for p in parsed_files:
            try:
                latest_mtime = max(latest_mtime, p.stat().st_mtime)
            except Exception:
                continue
        cached = self._parsed_cache.get(cache_key)
        if cached and cached[0] == latest_mtime:
            return list(cached[1])
        chunks: list[str] = []
        for p in parsed_files:
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                doc_chunks = data.get("chunks") or []
                for c in doc_chunks:
                    if isinstance(c, str) and c.strip():
                        chunks.append(c)
            except Exception:
                continue
        self._parsed_cache[cache_key] = (latest_mtime, list(chunks))
        return chunks

    _WIKI_STALE_HOURS = 72

    def _load_wiki_chunks(self, project_id: str | None) -> list[str]:
        """Load wiki pages as ranked text chunks for context injection.

        Wiki pages are LLM-enriched summaries — higher signal than raw parsed_docs.
        Each chunk is prefixed with its page title so the agent knows the source.
        Pages older than _WIKI_STALE_HOURS get a [STALE] prefix so agents can weight them
        accordingly. Results are mtime-cached to avoid re-reading on every call.
        """
        if not project_id:
            return []
        wiki_dir = workspace_path(project_id) / "wiki"
        if not wiki_dir.exists():
            return []
        _skip = {"index.md", "log.md"}
        md_files = [f for f in wiki_dir.glob("*.md") if f.name not in _skip]

        # Mtime cache — re-read only when any file has changed.
        cache_key = str(wiki_dir)
        latest_mtime = 0.0
        for f in md_files:
            try:
                latest_mtime = max(latest_mtime, f.stat().st_mtime)
            except Exception:
                continue
        cached = self._wiki_cache.get(cache_key)
        if cached and cached[0] == latest_mtime:
            return list(cached[1])

        now = time.time()
        stale_threshold = self._WIKI_STALE_HOURS * 3600
        chunks: list[str] = []
        for md_file in md_files:
            try:
                content = md_file.read_text(encoding="utf-8")
                title_match = re.search(r'^title:\s*"?([^"\n]+)"?', content, re.MULTILINE)
                title = title_match.group(1) if title_match else md_file.stem.replace("_", " ").title()
                body = re.sub(r"^---.*?---\s*", "", content, flags=re.DOTALL).strip()
                if not body:
                    continue
                try:
                    age_s = now - md_file.stat().st_mtime
                    if age_s > stale_threshold:
                        age_h = int(age_s / 3600)
                        body = f"[STALE: {age_h}h old]\n{body}"
                except Exception:
                    pass
                chunks.append(f"[Wiki: {title}]\n{body}")
            except Exception:
                continue
        self._wiki_cache[cache_key] = (latest_mtime, list(chunks))
        return chunks

    def _bm25_scores(self, chunks: list[str], query: str) -> list[float]:
        tokenized = [_tokenize(c) for c in chunks]
        n_docs = len(chunks)
        if n_docs == 0:
            return []

        df: dict[str, int] = {}
        dl = [len(toks) for toks in tokenized]
        avgdl = (sum(dl) / n_docs) if n_docs else 0.0
        if avgdl <= 0:
            return [0.0 for _ in chunks]

        for toks in tokenized:
            seen = set(toks)
            for term in seen:
                df[term] = df.get(term, 0) + 1

        q_terms = _tokenize(query)
        if not q_terms:
            return [0.0 for _ in chunks]

        # Precompute IDF for query terms.
        idf: dict[str, float] = {}
        for term in set(q_terms):
            dfi = df.get(term, 0)
            idf[term] = math.log((n_docs - dfi + 0.5) / (dfi + 0.5) + 1.0)

        # Compute scores.
        scores: list[float] = [0.0 for _ in chunks]
        k1 = self.k1
        b = self.b

        for i, toks in enumerate(tokenized):
            if not toks:
                continue
            tf: dict[str, int] = {}
            for t in toks:
                tf[t] = tf.get(t, 0) + 1
            score = 0.0
            for term in q_terms:
                if term not in idf:
                    continue
                term_tf = tf.get(term, 0)
                if term_tf <= 0:
                    continue
                denom = term_tf + k1 * (1 - b + b * (dl[i] / avgdl))
                score += idf[term] * ((term_tf * (k1 + 1)) / denom)
            scores[i] = score
        return scores

    def _mmr_select(
        self,
        candidates: list[tuple[int, float]],
        chunks: list[str],
        *,
        max_chars: int,
        lambda_param: float = 0.7,
        max_items: int = 15,
    ) -> list[int]:
        """
        Select candidates using an MMR-like objective:
        lambda * relevance - (1-lambda) * diversity

        Diversity is approximated with Jaccard similarity over token sets.
        """

        selected: list[int] = []
        selected_token_sets: list[set[str]] = []

        def jaccard(a: set[str], b: set[str]) -> float:
            if not a or not b:
                return 0.0
            return len(a & b) / len(a | b)

        for _ in range(max_items):
            best_idx: int | None = None
            best_score = -1e9

            for idx, rel in candidates:
                if idx in selected:
                    continue
                cand_tokens = set(_tokenize(chunks[idx]))
                if not selected_token_sets:
                    diversity = 0.0
                else:
                    diversity = max(jaccard(cand_tokens, tset) for tset in selected_token_sets)

                mmr = lambda_param * float(rel) - (1 - lambda_param) * diversity
                if mmr > best_score:
                    best_score = mmr
                    best_idx = idx

            if best_idx is None:
                break

            selected.append(best_idx)
            selected_token_sets.append(set(_tokenize(chunks[best_idx])))

            current_chars = sum(len(chunks[i]) for i in selected)
            if current_chars >= max_chars:
                break

        return selected

    def _expand_queries(self, instruction: str) -> list[str]:
        ins = (instruction or "").strip()
        if not ins:
            return []
        # Deterministic "expansion" placeholders. LP/web_search + embeddings can improve this later.
        return [
            ins,
            f"{ins} roles steps decisions",
            f"{ins} best practices standards frameworks",
        ]

    def assemble(
        self,
        project_id: str | None,
        instruction: str,
        *,
        lp_snippets: list[str] | None = None,
        style_context: str | None = None,
    ) -> ContextBundle:
        context_md = ""
        if project_id:
            try:
                context_md = (workspace_path(project_id) / "CONTEXT.md").read_text(encoding="utf-8")
            except FileNotFoundError:
                context_md = ""

        if style_context:
            context_md = f"{context_md}\n\n{style_context}".strip()

        lp_snippets = lp_snippets or []

        tier0 = (context_md or instruction)[:2000]
        tier1 = "\n".join(lp_snippets)[:12000]

        chunks = self._load_all_parsed_chunks(project_id) if project_id else []
        if not chunks:
            tier2 = instruction[:10000]
            combined = "\n\n".join([tier0, tier1, tier2])[:32000]
            return ContextBundle(text=combined)

        # Multi-query expansion + BM25 candidate scoring.
        queries = self._expand_queries(instruction)
        top_k_per_query = 20
        candidates: dict[int, float] = {}
        for q in queries:
            scores = self._bm25_scores(chunks, q)
            for idx, sc in enumerate(scores):
                if sc <= 0:
                    continue
                # Keep only the best relevance score seen for this chunk across queries.
                prev = candidates.get(idx)
                if prev is None or sc > prev:
                    candidates[idx] = float(sc)

            # Keep candidate set bounded.
            if len(candidates) > 60:
                # Trim by highest relevance scores.
                top = sorted(candidates.items(), key=lambda kv: kv[1], reverse=True)[:60]
                candidates = dict(top)

        # Convert to list and MMR-select.
        candidate_list = sorted(candidates.items(), key=lambda kv: kv[1], reverse=True)[:60]
        selected_idxs = self._mmr_select(
            candidate_list,
            chunks,
            max_chars=10000,
        )
        tier2 = "\n".join(chunks[i] for i in selected_idxs)[:10000]

        combined = "\n\n".join([tier0, tier1, tier2])[:32000]
        return ContextBundle(text=combined)

    def planner_excerpt(
        self,
        project_id: str | None,
        query_text: str,
        *,
        char_cap: int,
    ) -> str:
        """
        BM25+MMR ranked chunk text for coordinator planning only (query-aligned, bounded size).
        """
        qt = (query_text or "").strip()
        if not project_id or not qt:
            return ""
        cap = max(500, int(char_cap))
        queries = self._expand_queries(qt)

        # Wiki pages first (curated context, up to 40% of planner budget)
        wiki_chunks = self._load_wiki_chunks(project_id)
        wiki_text = ""
        if wiki_chunks:
            wiki_scores = self._bm25_scores(wiki_chunks, qt)
            wiki_candidates = sorted(enumerate(wiki_scores), key=lambda kv: kv[1], reverse=True)[:10]
            wiki_budget = min(4000, cap * 2 // 5)
            if not any(score > 0 for _, score in wiki_candidates):
                wiki_sel = list(range(min(3, len(wiki_chunks))))
            else:
                wiki_sel = self._mmr_select(wiki_candidates, wiki_chunks, max_chars=wiki_budget)
            wiki_text = "\n\n---\n\n".join(wiki_chunks[i] for i in wiki_sel)

        chunks = self._load_all_parsed_chunks(project_id)
        doc_text = ""
        if chunks:
            candidates: dict[int, float] = {}
            for q in queries:
                scores = self._bm25_scores(chunks, q)
                for idx, sc in enumerate(scores):
                    if sc <= 0:
                        continue
                    prev = candidates.get(idx)
                    if prev is None or sc > prev:
                        candidates[idx] = float(sc)
                if len(candidates) > 60:
                    top = sorted(candidates.items(), key=lambda kv: kv[1], reverse=True)[:60]
                    candidates = dict(top)
            candidate_list = sorted(candidates.items(), key=lambda kv: kv[1], reverse=True)[:60]
            doc_budget = max(400, cap - len(wiki_text) - len("## Planner retrieval excerpt\n\n"))
            selected_idxs = self._mmr_select(candidate_list, chunks, max_chars=doc_budget)
            doc_text = "\n\n---\n\n".join(chunks[i] for i in selected_idxs)

        if not wiki_text and not doc_text:
            return ""

        parts = [p for p in [wiki_text, doc_text] if p]
        header = "## Planner retrieval excerpt\n\n"
        return (header + "\n\n---\n\n".join(parts))[:cap]

    @staticmethod
    def _compact_items(items: list[str], max_chars: int) -> tuple[list[str], int]:
        used = 0
        out: list[str] = []
        dropped = 0
        for item in items:
            clean = (item or "").strip()
            if not clean:
                continue
            if used + len(clean) + 1 > max_chars:
                dropped += 1
                continue
            out.append(clean)
            used += len(clean) + 1
        return out, dropped

    @staticmethod
    def _snip_oldest(items: list[str], keep_count: int) -> tuple[list[str], int]:
        """Tier 2 compaction: keep newest N items, drop oldest overflow."""
        if keep_count <= 0:
            return [], len(items)
        if len(items) <= keep_count:
            return list(items), 0
        dropped = len(items) - keep_count
        return list(items[-keep_count:]), dropped

    @staticmethod
    def _auto_summary(items: list[str], max_items: int = 8, max_chars: int = 1200) -> str:
        """Tier 3 compaction: light-weight summary of the latest high-signal entries."""
        if not items:
            return ""
        tail = [str(x).strip() for x in items[-max_items:] if str(x).strip()]
        if not tail:
            return ""
        lines = [f"- {t}" for t in tail]
        summary = "Recent memory summary:\n" + "\n".join(lines)
        return summary[:max_chars]

    @staticmethod
    def _parse_dropped_sources(dropped_text: str) -> dict[str, list[str]]:
        """Extract wiki page titles and LP headings from text that was hard-trimmed."""
        wiki_titles = re.findall(r"\[Wiki:\s*([^\]]+)\]", dropped_text)
        lp_headings = re.findall(r"\[LP\]([^\n]+)", dropped_text)
        return {
            "wiki_pages": [t.strip() for t in wiki_titles],
            "lp_headings": [h.strip() for h in lp_headings],
        }

    @staticmethod
    def _context_collapse(
        sections: dict[str, str], char_cap: int
    ) -> tuple[dict[str, str], bool, dict[str, object]]:
        """
        Tier 4 compaction: keep only essential sections under strict budget.
        Preserves objective/non-negotiables/failures and truncates evidence aggressively.
        Returns the collapsed sections, a flag that collapse was applied, and a dict of
        dropped source names (wiki pages / LP headings) for observability.
        """
        hard_cap = max(2000, int(char_cap * 0.55))
        collapsed = {
            "ObjectiveNow": str(sections.get("ObjectiveNow") or "")[:700],
            "NonNegotiables": str(sections.get("NonNegotiables") or "")[:1100],
            "WhatChanged": str(sections.get("WhatChanged") or "")[:700],
            "Evidence": str(sections.get("Evidence") or "")[:1200],
            "KnownFailures": str(sections.get("KnownFailures") or "")[:700],
        }
        dropped_sources: dict[str, object] = {}
        text = (
            "## ObjectiveNow\n"
            f"{collapsed['ObjectiveNow']}\n\n"
            "## NonNegotiables\n"
            f"{collapsed['NonNegotiables']}\n\n"
            "## WhatChanged\n"
            f"{collapsed['WhatChanged']}\n\n"
            "## Evidence\n"
            f"{collapsed['Evidence']}\n\n"
            "## KnownFailures\n"
            f"{collapsed['KnownFailures']}"
        )
        if len(text) <= hard_cap:
            return collapsed, True, dropped_sources
        # Final hard trim on evidence first, then what changed.
        overflow = len(text) - hard_cap
        if overflow > 0:
            evidence_before = collapsed["Evidence"]
            collapsed["Evidence"] = evidence_before[: max(0, len(evidence_before) - overflow)]
            dropped_evidence = evidence_before[len(collapsed["Evidence"]):]
            if dropped_evidence:
                dropped_sources["Evidence"] = TieredContextEngine._parse_dropped_sources(dropped_evidence)
        text = (
            "## ObjectiveNow\n"
            f"{collapsed['ObjectiveNow']}\n\n"
            "## NonNegotiables\n"
            f"{collapsed['NonNegotiables']}\n\n"
            "## WhatChanged\n"
            f"{collapsed['WhatChanged']}\n\n"
            "## Evidence\n"
            f"{collapsed['Evidence']}\n\n"
            "## KnownFailures\n"
            f"{collapsed['KnownFailures']}"
        )
        if len(text) > hard_cap:
            over2 = len(text) - hard_cap
            wc_before = collapsed["WhatChanged"]
            collapsed["WhatChanged"] = wc_before[: max(0, len(wc_before) - over2)]
            dropped_wc = wc_before[len(collapsed["WhatChanged"]):]
            if dropped_wc:
                dropped_sources["WhatChanged"] = TieredContextEngine._parse_dropped_sources(dropped_wc)
        return collapsed, True, dropped_sources

    def assemble_v2(
        self,
        project_id: str | None,
        instruction: str,
        *,
        run_memory_events: list[dict[str, object]] | None = None,
        project_profile: dict[str, object] | None = None,
        lp_snippets: list[str] | None = None,
        char_cap: int = 32000,
    ) -> ContextBundle:
        # Approximation: token ~= 4 chars, used for budgeting signals.
        token_budget = max(500, int(char_cap / 4))
        section_caps = {
            "ObjectiveNow": min(3500, max(1200, int(char_cap * 0.16))),
            "NonNegotiables": min(5500, max(1800, int(char_cap * 0.22))),
            "WhatChanged": min(5000, max(1400, int(char_cap * 0.18))),
            "Evidence": min(14000, max(6000, int(char_cap * 0.34))),
            "KnownFailures": min(4000, max(1200, int(char_cap * 0.1))),
        }

        objective_items = [instruction.strip()] if (instruction or "").strip() else []
        non_negotiables = []
        long_term_items = []
        user_preference_lines: list[str] = []
        if isinstance(project_profile, dict):
            values = project_profile.get("non_negotiables")
            if isinstance(values, list):
                non_negotiables = [str(v).strip() for v in values if str(v).strip()]
            ltm = project_profile.get("long_term_items")
            if isinstance(ltm, list):
                long_term_items = [str(v).strip() for v in ltm if str(v).strip()]
            upl = project_profile.get("user_preference_lines")
            if isinstance(upl, list):
                user_preference_lines = [str(v).strip() for v in upl if str(v).strip()]

        changes: list[str] = []
        failures: list[str] = []
        compaction_trace: list[str] = ["tier1_micro_compact"]
        for ev in run_memory_events or []:
            if not isinstance(ev, dict):
                continue
            et = str(ev.get("event_type") or "")
            payload = ev.get("payload")
            body = payload if isinstance(payload, dict) else {"value": str(payload)}
            summary = str(body.get("summary") or body.get("status") or body.get("value") or "").strip()
            if not summary:
                continue
            if et in {
                "qa_outcome",
                "qa_remediation",
                "guardrail_outcome",
                "user_intent_updated",
                "artifact_summary",
            }:
                changes.append(f"{et}: {summary}")
            if et in {"qa_remediation", "guardrail_outcome"}:
                failures.append(f"{et}: {summary}")
        # Tier 2: snip oldest change/failure trails before section-level compaction.
        changes, changes_snipped = self._snip_oldest(changes, keep_count=120)
        failures, failures_snipped = self._snip_oldest(failures, keep_count=80)
        if changes_snipped or failures_snipped:
            compaction_trace.append("tier2_snip")

        context_md = ""
        if project_id:
            try:
                context_md = (workspace_path(project_id) / "CONTEXT.md").read_text(encoding="utf-8")
            except FileNotFoundError:
                context_md = ""

        selected_lp_info: list[dict[str, object]] = []
        lp_list = [s for s in (lp_snippets or []) if isinstance(s, str) and s.strip()]
        for snippet in lp_list:
            heading_line = snippet.split("\n")[0]
            heading = heading_line[4:].strip() if heading_line.startswith("[LP]") else heading_line
            selected_lp_info.append({"heading": heading, "chars": len(snippet)})

        evidence_input = [s for s in [context_md, *lp_list] if isinstance(s, str) and s.strip()]

        # Wiki pages (curated, LLM-enriched) — injected before raw parsed_docs so they
        # get priority when the Evidence budget is tight.
        selected_wiki_info: list[dict[str, object]] = []
        wiki_chunks = self._load_wiki_chunks(project_id) if project_id else []
        if wiki_chunks:
            wiki_scores = self._bm25_scores(wiki_chunks, instruction or "")
            wiki_candidates = sorted(enumerate(wiki_scores), key=lambda kv: kv[1], reverse=True)[:20]
            wiki_budget = min(8000, section_caps["Evidence"] // 2)
            if not any(score > 0 for _, score in wiki_candidates):
                wiki_selected = list(range(min(5, len(wiki_chunks))))
            else:
                wiki_selected = self._mmr_select(wiki_candidates, wiki_chunks, max_chars=wiki_budget)
            for i in wiki_selected:
                chunk = wiki_chunks[i]
                m = re.search(r"\[Wiki:\s*([^\]]+)\]", chunk)
                selected_wiki_info.append({"title": m.group(1).strip() if m else "unknown", "chars": len(chunk)})
            evidence_input.extend(wiki_chunks[i] for i in wiki_selected)

        chunks = self._load_all_parsed_chunks(project_id) if project_id else []
        if chunks:
            scores = self._bm25_scores(chunks, instruction or "")
            candidate_list = sorted(enumerate(scores), key=lambda kv: kv[1], reverse=True)[:60]
            if not any(score > 0 for _, score in candidate_list):
                selected_idxs = list(range(min(12, len(chunks))))
            else:
                selected_idxs = self._mmr_select(candidate_list, chunks, max_chars=section_caps["Evidence"])
            evidence_input.extend(chunks[i] for i in selected_idxs)

        objective_out, obj_dropped = self._compact_items(objective_items, section_caps["ObjectiveNow"])
        nonneg_out, nonneg_dropped = self._compact_items(
            [*non_negotiables, *long_term_items, *user_preference_lines],
            section_caps["NonNegotiables"],
        )
        changed_out, changed_dropped = self._compact_items(changes, section_caps["WhatChanged"])
        evidence_out, evidence_dropped = self._compact_items(evidence_input, section_caps["Evidence"])
        failures_out, fail_dropped = self._compact_items(failures, section_caps["KnownFailures"])
        if changed_dropped or evidence_dropped or fail_dropped or nonneg_dropped or obj_dropped:
            compaction_trace.append("tier3_auto_compact")

        sections = {
            "ObjectiveNow": "\n".join(objective_out),
            "NonNegotiables": "\n".join(nonneg_out),
            "WhatChanged": "\n".join(changed_out),
            "Evidence": "\n".join(evidence_out),
            "KnownFailures": "\n".join(failures_out),
        }

        # Tier 3 fallback signal: inject short summary when change/failure lists were compacted.
        auto_summary = ""
        if changed_dropped or fail_dropped:
            auto_summary = self._auto_summary([*changes, *failures], max_items=10, max_chars=900)
            if auto_summary:
                sections["WhatChanged"] = (
                    (sections["WhatChanged"] + "\n\n" + auto_summary).strip()
                    if sections["WhatChanged"]
                    else auto_summary
                )

        assembled = (
            "## ObjectiveNow\n"
            f"{sections['ObjectiveNow']}\n\n"
            "## NonNegotiables\n"
            f"{sections['NonNegotiables']}\n\n"
            "## WhatChanged\n"
            f"{sections['WhatChanged']}\n\n"
            "## Evidence\n"
            f"{sections['Evidence']}\n\n"
            "## KnownFailures\n"
            f"{sections['KnownFailures']}"
        )[:char_cap]
        tier4_applied = False
        tier4_dropped_sources: dict[str, object] = {}
        if len(assembled) >= char_cap:
            collapsed, tier4_applied, tier4_dropped_sources = self._context_collapse(sections, char_cap=char_cap)
            sections = collapsed
            assembled = (
                "## ObjectiveNow\n"
                f"{sections['ObjectiveNow']}\n\n"
                "## NonNegotiables\n"
                f"{sections['NonNegotiables']}\n\n"
                "## WhatChanged\n"
                f"{sections['WhatChanged']}\n\n"
                "## Evidence\n"
                f"{sections['Evidence']}\n\n"
                "## KnownFailures\n"
                f"{sections['KnownFailures']}"
            )[:char_cap]
        if tier4_applied:
            compaction_trace.append("tier4_context_collapse")
        metadata = {
            "char_cap": char_cap,
            "token_budget_estimate": token_budget,
            "token_count_estimate": int(len(assembled) / 4),
            "parsed_chunk_count": len(chunks),
            "selected_evidence_chunk_count": len(evidence_out),
            "section_sizes": {k: len(v) for k, v in sections.items()},
            "compaction_tiers_applied": compaction_trace,
            "compaction_reason_codes": [
                "overflow_detected" if tier4_applied else "quality_preserve",
                "overflow_predicted" if (changed_dropped or evidence_dropped or fail_dropped) else "quality_preserve",
            ],
            "snipped_items": {
                "WhatChanged": changes_snipped,
                "KnownFailures": failures_snipped,
            },
            "auto_summary_applied": bool(auto_summary),
            "context_collapse_applied": tier4_applied,
            "dropped_items": {
                "ObjectiveNow": obj_dropped,
                "NonNegotiables": nonneg_dropped,
                "WhatChanged": changed_dropped,
                "Evidence": evidence_dropped,
                "KnownFailures": fail_dropped,
            },
            "context_provenance": {
                "selected_wiki_pages": selected_wiki_info,
                "selected_lp_headings": selected_lp_info,
                "parsed_doc_count": len(chunks),
            },
            "tier4_dropped_sources": tier4_dropped_sources,
        }
        return ContextBundle(text=assembled, char_budget=char_cap, metadata=metadata)
