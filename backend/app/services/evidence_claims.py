"""Content-level evidence claim HITL — per-claim accept/reject before final approve.

After render, unsupported (and grounded) numeric claims are written to
``evidence_claims.json``. Reviewers accept (keep / caveat as assumption) or
reject (must be removed or re-sourced) each claim. Final approve is blocked
while any claim remains ``pending``.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

CLAIMS_FILENAME = "evidence_claims.json"
_VALID_DECISIONS = frozenset({"accept", "reject", "pending"})


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _claim_id(slide_index: int, claim: str, source: str) -> str:
    raw = f"{source}:{slide_index}:{claim}".lower().strip()
    return f"ec_{uuid.uuid5(uuid.NAMESPACE_URL, raw).hex[:12]}"


def build_claims_from_evidence_report(
    evidence_report: dict[str, Any] | None,
    *,
    source: str = "pptx",
) -> list[dict[str, Any]]:
    """Flatten slide validations into a reviewable claim list."""
    if not isinstance(evidence_report, dict):
        return []
    claims: list[dict[str, Any]] = []
    for i, sv in enumerate(evidence_report.get("slide_validations") or [], start=1):
        if not isinstance(sv, dict):
            continue
        validation = sv.get("validation") if isinstance(sv.get("validation"), dict) else {}
        title = str(sv.get("slide_title") or f"Slide {i}")
        for uc in validation.get("unsupported_claims") or []:
            if not isinstance(uc, dict):
                continue
            claim_text = str(uc.get("claim") or "").strip()
            if not claim_text:
                continue
            claims.append({
                "id": _claim_id(i, claim_text, source),
                "source": source,
                "slide_index": i,
                "slide_title": title,
                "claim": claim_text,
                "claim_type": str(uc.get("type") or "Unknown"),
                "context": str(uc.get("context") or "")[:240],
                "status": "unsupported",
                "decision": "pending",
                "citation": None,
            })
        for gc in validation.get("grounded_claims") or []:
            if not isinstance(gc, dict):
                continue
            claim_text = str(gc.get("claim") or "").strip()
            if not claim_text:
                continue
            claims.append({
                "id": _claim_id(i, f"g:{claim_text}", source),
                "source": source,
                "slide_index": i,
                "slide_title": title,
                "claim": claim_text,
                "claim_type": "Grounded",
                "context": "",
                "status": "grounded",
                "decision": "accept",  # grounded claims default-accepted
                "citation": gc.get("citation") or gc.get("source_id"),
            })
    return claims


def write_claims_dossier(
    run_dir: Path,
    evidence_report: dict[str, Any] | None,
    *,
    source: str = "pptx",
) -> dict[str, Any]:
    """Persist (or merge) the claim dossier for a run. Preserves prior decisions."""
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / CLAIMS_FILENAME
    prior = load_claims_dossier(run_dir)
    prior_by_id = {
        str(c.get("id")): c
        for c in (prior.get("claims") or [])
        if isinstance(c, dict) and c.get("id")
    }

    fresh = build_claims_from_evidence_report(evidence_report, source=source)
    merged: list[dict[str, Any]] = []
    for claim in fresh:
        old = prior_by_id.get(claim["id"])
        if old and old.get("decision") in {"accept", "reject"}:
            claim = {**claim, "decision": old["decision"], "decided_at": old.get("decided_at")}
            if old.get("note"):
                claim["note"] = old["note"]
        merged.append(claim)

    # Keep decisions for claims from other sources (e.g. docx) not in this report.
    for cid, old in prior_by_id.items():
        if any(c["id"] == cid for c in merged):
            continue
        if str(old.get("source") or "") != source:
            merged.append(old)

    dossier = {
        "updated_at": _now_iso(),
        "claims": merged,
        "summary": _summarize(merged),
    }
    path.write_text(json.dumps(dossier, indent=2), encoding="utf-8")
    return dossier


def load_claims_dossier(run_dir: Path) -> dict[str, Any]:
    path = Path(run_dir) / CLAIMS_FILENAME
    if not path.is_file():
        return {"claims": [], "summary": _summarize([])}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {"claims": [], "summary": _summarize([])}
        claims = [c for c in (data.get("claims") or []) if isinstance(c, dict)]
        data["claims"] = claims
        data["summary"] = _summarize(claims)
        return data
    except Exception as exc:  # noqa: BLE001
        logger.warning("could not load evidence claims from %s: %s", path, exc)
        return {"claims": [], "summary": _summarize([])}


def apply_claim_decisions(
    run_dir: Path,
    decisions: list[dict[str, Any]],
    *,
    actor: str | None = None,
) -> dict[str, Any]:
    """Apply accept/reject decisions keyed by claim id."""
    dossier = load_claims_dossier(run_dir)
    by_id = {str(c.get("id")): c for c in dossier.get("claims") or [] if c.get("id")}
    applied = 0
    for item in decisions:
        if not isinstance(item, dict):
            continue
        cid = str(item.get("id") or "").strip()
        decision = str(item.get("decision") or "").strip().lower()
        if cid not in by_id or decision not in _VALID_DECISIONS:
            continue
        by_id[cid]["decision"] = decision
        by_id[cid]["decided_at"] = _now_iso()
        if actor:
            by_id[cid]["decided_by"] = actor
        note = str(item.get("note") or "").strip()
        if note:
            by_id[cid]["note"] = note[:500]
        applied += 1

    claims = list(by_id.values())
    dossier = {
        "updated_at": _now_iso(),
        "claims": claims,
        "summary": _summarize(claims),
        "last_applied": applied,
    }
    path = Path(run_dir) / CLAIMS_FILENAME
    path.write_text(json.dumps(dossier, indent=2), encoding="utf-8")
    return dossier


def pending_unsupported_count(dossier: dict[str, Any] | None) -> int:
    if not isinstance(dossier, dict):
        return 0
    return sum(
        1
        for c in dossier.get("claims") or []
        if isinstance(c, dict)
        and c.get("status") == "unsupported"
        and c.get("decision") == "pending"
    )


def _summarize(claims: list[dict[str, Any]]) -> dict[str, int]:
    summary = {
        "total": len(claims),
        "unsupported": 0,
        "grounded": 0,
        "pending": 0,
        "accepted": 0,
        "rejected": 0,
    }
    for c in claims:
        if not isinstance(c, dict):
            continue
        st = str(c.get("status") or "")
        if st == "unsupported":
            summary["unsupported"] += 1
        elif st == "grounded":
            summary["grounded"] += 1
        dec = str(c.get("decision") or "pending")
        if dec == "pending" and st == "unsupported":
            summary["pending"] += 1
        elif dec == "accept":
            summary["accepted"] += 1
        elif dec == "reject":
            summary["rejected"] += 1
    return summary
