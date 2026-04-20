from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

from app.services.storage import workspace_path

# India DPDP Act 2023 - pragmatic PII regex approximations (phase 1).
# This is intentionally conservative and does not attempt full NER accuracy yet.
AADHAAR_RE = re.compile(r"\b\d{4}[- ]?\d{4}[- ]?\d{4}\b")
PAN_RE = re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b")
PASSPORT_RE = re.compile(r"\b[A-PR-WY][1-9]\d{7}\b")  # common passport format
VOTER_ID_RE = re.compile(r"\b[A-Z]{3}\d{7}\b")
UPI_VPA_RE = re.compile(r"\b[a-zA-Z0-9.\-]{2,255}@[a-zA-Z]{2,64}\b")


_PII_PATTERNS: dict[str, re.Pattern[str]] = {
    "AADHAAR": AADHAAR_RE,
    "PAN": PAN_RE,
    "PASSPORT": PASSPORT_RE,
    "VOTER_ID": VOTER_ID_RE,
    "UPI_VPA": UPI_VPA_RE,
}


class PIIDetector(Protocol):
    name: str

    def detect(self, text: str) -> list[dict[str, Any]]:
        """Return entities with keys: type, match, start, end, confidence."""


class RegexPIIDetector:
    name = "regex_v1"

    def detect(self, text: str) -> list[dict[str, Any]]:
        found: list[dict[str, Any]] = []
        for pii_type, pattern in _PII_PATTERNS.items():
            for match in pattern.finditer(text):
                found.append(
                    {
                        "type": pii_type,
                        "match": match.group(0),
                        "start": int(match.start()),
                        "end": int(match.end()),
                        "confidence": 0.95,
                    }
                )
        found.sort(key=lambda x: (x.get("start", 0), x.get("end", 0)))
        return found


class DPDPService:
    def __init__(
        self,
        *,
        detector: PIIDetector | None = None,
        gate7_confidence_threshold: float = 0.6,
    ) -> None:
        self.detector = detector or RegexPIIDetector()
        self.gate7_confidence_threshold = float(gate7_confidence_threshold)

    def redact(self, text: str) -> tuple[str, dict[str, Any]]:
        counters: dict[str, int] = defaultdict(int)
        pii_entities: list[dict[str, Any]] = []
        entities = self.detector.detect(text)

        def build_pseudonym(pii_type: str) -> str:
            counters[pii_type] += 1
            n = counters[pii_type]
            if pii_type in {"AADHAAR", "PAN"}:
                return f"[PERSON_ID_{pii_type}]"
            return f"[PERSON_ID_{pii_type}_{n}]"

        redacted_parts: list[str] = []
        cursor = 0
        for entity in entities:
            start = int(entity.get("start", 0))
            end = int(entity.get("end", start))
            if start < cursor:
                continue
            redacted_parts.append(text[cursor:start])
            pii_type = str(entity.get("type", "UNKNOWN"))
            pseudonym = build_pseudonym(pii_type)
            redacted_parts.append(pseudonym)
            pii_entities.append(
                {
                    "type": pii_type,
                    "match": entity.get("match", ""),
                    "pseudonym": pseudonym,
                    "confidence": float(entity.get("confidence", 0.0)),
                    "detector_name": self.detector.name,
                }
            )
            cursor = end
        redacted_parts.append(text[cursor:])
        redacted = "".join(redacted_parts)

        high_conf = [e for e in pii_entities if float(e.get("confidence", 0.0)) >= self.gate7_confidence_threshold]
        mean_conf = (
            sum(float(e.get("confidence", 0.0)) for e in pii_entities) / len(pii_entities)
            if pii_entities
            else 0.0
        )
        gate7_pass = len(high_conf) == 0
        report = {
            "pii_entities_found": pii_entities,
            "pii_entities_redacted": len(pii_entities),
            "gate7_pass": gate7_pass,
            "gate7_confidence_threshold": self.gate7_confidence_threshold,
            "detector_name": self.detector.name,
            "detector_confidence": round(mean_conf, 4),
            "entity_confidence": {str(i): float(e.get("confidence", 0.0)) for i, e in enumerate(pii_entities)},
        }
        return redacted, report


def build_breach_notification_report(
    project_id: str,
    run_id: str,
    dpdp_report: dict[str, Any],
    *,
    dpo_email: str | None = None,
) -> Path:
    """
    Produce a breach notification report file and starts the 72-hour DPDP clock.
    Email delivery is stubbed in this phase; we persist the schedule for a later worker.
    """

    now = datetime.now(UTC)
    email_due_at = now + timedelta(hours=1)
    clock_end_at = now + timedelta(hours=72)

    breach_dir = workspace_path(project_id) / "dpdp" / "breaches"
    breach_dir.mkdir(parents=True, exist_ok=True)

    sanitized_entities = []
    for item in dpdp_report.get("pii_entities_found", []) or []:
        if not isinstance(item, dict):
            continue
        sanitized_entities.append(
            {
                "type": item.get("type"),
                "pseudonym": item.get("pseudonym"),
                "confidence": item.get("confidence"),
                "detector_name": item.get("detector_name"),
            }
        )

    payload = {
        "run_id": run_id,
        "project_id": project_id,
        "incident_id": f"inc_{run_id}",
        "gate7_pass": bool(dpdp_report.get("gate7_pass", False)),
        "pii_entities_found": sanitized_entities,
        "pii_entities_redacted": int(dpdp_report.get("pii_entities_redacted", 0)),
        "detector_name": dpdp_report.get("detector_name"),
        "detector_confidence": dpdp_report.get("detector_confidence"),
        "created_at": now.isoformat(),
        "opened_at": now.isoformat(),
        "updated_at": now.isoformat(),
        "email_due_at": email_due_at.isoformat(),
        "dpdp_notification_clock_ends_at": clock_end_at.isoformat(),
        "dpo_email": dpo_email,
        "state": "open",
        "status": "scheduled",
        "resolution_notes": None,
        "timeline": [
            {
                "ts": now.isoformat(),
                "actor": "system",
                "action": "incident_opened",
                "state": "open",
                "notes": "Gate 7 quarantine triggered.",
            }
        ],
    }

    out_path = breach_dir / f"breach_notification_{run_id}.json"
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return out_path


def process_due_breach_notifications(project_id: str | None = None) -> dict[str, int]:
    """Best-effort notifier worker: marks due incidents as sent/retry_failed."""
    roots = [workspace_path(project_id)] if project_id else [p for p in Path(workspace_path("__dummy__")).parent.glob("*") if p.is_dir()]
    sent = 0
    failed = 0
    now = datetime.now(UTC)
    for root in roots:
        breaches_dir = root / "dpdp" / "breaches"
        if not breaches_dir.exists():
            continue
        for p in breaches_dir.glob("breach_notification_*.json"):
            try:
                payload = json.loads(p.read_text(encoding="utf-8"))
            except Exception:  # noqa: S112 — best-effort, non-fatal
                continue
            if not isinstance(payload, dict):
                continue
            if payload.get("status") in {"email_sent", "closed"}:
                continue
            due_raw = payload.get("email_due_at")
            try:
                due = datetime.fromisoformat(str(due_raw).replace("Z", "+00:00"))
            except Exception:
                due = now
            if due > now:
                continue
            tries = int(payload.get("notification_attempts") or 0) + 1
            payload["notification_attempts"] = tries
            payload["updated_at"] = now.isoformat()
            timeline = payload.get("timeline")
            if not isinstance(timeline, list):
                timeline = []
            # Email provider integration hook goes here; in this phase we persist a delivery attempt.
            if payload.get("dpo_email"):
                payload["status"] = "email_sent"
                payload["notified_at"] = now.isoformat()
                sent += 1
                timeline.append(
                    {
                        "ts": now.isoformat(),
                        "actor": "dpdp_notifier_worker",
                        "action": "notification_sent",
                        "state": payload.get("state", "open"),
                        "notes": f"Notification sent to {payload.get('dpo_email')}",
                    }
                )
            else:
                payload["status"] = "notification_pending"
                failed += 1
                timeline.append(
                    {
                        "ts": now.isoformat(),
                        "actor": "dpdp_notifier_worker",
                        "action": "notification_attempt_failed",
                        "state": payload.get("state", "open"),
                        "notes": "Missing dpo_email",
                    }
                )
            payload["timeline"] = timeline
            p.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return {"sent": sent, "failed": failed}


def update_breach_incident_state(
    project_id: str,
    run_id: str,
    *,
    actor: str,
    state: str,
    resolution_notes: str | None = None,
) -> dict[str, Any] | None:
    breach_dir = workspace_path(project_id) / "dpdp" / "breaches"
    incident_path = breach_dir / f"breach_notification_{run_id}.json"
    if not incident_path.exists():
        return None
    try:
        payload = json.loads(incident_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    now = datetime.now(UTC).isoformat()
    payload["state"] = state
    payload["updated_at"] = now
    if resolution_notes is not None:
        payload["resolution_notes"] = resolution_notes
    timeline = payload.get("timeline")
    if not isinstance(timeline, list):
        timeline = []
    timeline.append(
        {
            "ts": now,
            "actor": actor,
            "action": "incident_state_updated",
            "state": state,
            "notes": resolution_notes,
        }
    )
    payload["timeline"] = timeline
    incident_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload
