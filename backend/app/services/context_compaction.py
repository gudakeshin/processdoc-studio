"""Tiered conversation compaction for large HITL digests."""

from __future__ import annotations

from dataclasses import dataclass
import re

from app.services.compaction_trace import CompactionTrace

_FRAGMENT_RE = re.compile(r"^(ok|okay|thanks|thank you|got it|yep|sure|done)[.! ]*$", re.IGNORECASE)


@dataclass(slots=True)
class CompactionLine:
    source_id: str
    text: str


class TieredCompactor:
    """Apply progressive compression tiers until text fits char budget."""

    def __init__(self, *, per_message_chars: int = 600) -> None:
        self._per_message_chars = max(120, int(per_message_chars))

    def assemble(self, *, lines: list[CompactionLine], char_cap: int) -> tuple[str, CompactionTrace]:
        cap = max(200, int(char_cap))
        trace = CompactionTrace()
        trace.original_char_count = self._joined_len(lines)

        current = list(lines)
        if trace.original_char_count <= cap:
            digest = self._join(current, cap)
            trace.final_char_count = len(digest)
            return digest, trace

        current = self._tier1_micro_compact(current, trace)
        if self._joined_len(current) > cap:
            current = self._tier2_snip_oldest(current, trace, keep_newest=120)
        if self._joined_len(current) > cap:
            current = self._tier3_auto_summary(current, trace)
        if self._joined_len(current) > cap:
            current = self._tier4_context_collapse(current, trace)

        digest = self._join(current, cap)
        trace.final_char_count = len(digest)
        return digest, trace

    def _tier1_micro_compact(
        self, lines: list[CompactionLine], trace: CompactionTrace
    ) -> list[CompactionLine]:
        result: list[CompactionLine] = []
        changed = False
        for line in lines:
            text = line.text.strip()
            if self._is_fragment(text):
                trace.drop_source("conversation_segments", line.source_id)
                changed = True
                continue
            if len(text) > self._per_message_chars:
                text = text[: self._per_message_chars] + "…"
                changed = True
            result.append(CompactionLine(source_id=line.source_id, text=text))
        if changed:
            trace.add_tier("tier1_micro_compact")
        return result

    def _tier2_snip_oldest(
        self, lines: list[CompactionLine], trace: CompactionTrace, *, keep_newest: int
    ) -> list[CompactionLine]:
        if len(lines) <= keep_newest:
            return lines
        dropped = lines[: len(lines) - keep_newest]
        kept = lines[len(lines) - keep_newest :]
        for line in dropped:
            trace.drop_source("conversation_segments", line.source_id)
        trace.add_tier("tier2_snip_oldest")
        return kept

    def _tier3_auto_summary(
        self, lines: list[CompactionLine], trace: CompactionTrace
    ) -> list[CompactionLine]:
        if len(lines) <= 8:
            return lines
        head = lines[:-8]
        tail = lines[-8:]
        summary_bits = [line.text for line in tail if not self._is_fragment(line.text)]
        summary_text = " | ".join(summary_bits)[:1200].strip()
        if not summary_text:
            return lines
        for line in head:
            trace.drop_source("conversation_segments", line.source_id)
        trace.add_tier("tier3_auto_summary")
        return [CompactionLine(source_id="summary:last8", text=f"[summary]: {summary_text}"), *tail]

    def _tier4_context_collapse(
        self, lines: list[CompactionLine], trace: CompactionTrace
    ) -> list[CompactionLine]:
        if not lines:
            return lines
        keep = lines[-5:]
        dropped = lines[: max(0, len(lines) - len(keep))]
        for line in dropped:
            trace.drop_source("conversation_segments", line.source_id)
        trace.add_tier("tier4_context_collapse")
        collapse = CompactionLine(
            source_id="collapse:context",
            text=(
                "[context-collapse]: Preserved latest high-signal turns only. "
                "Older turns were compacted to fit budget."
            ),
        )
        return [collapse, *keep]

    def _join(self, lines: list[CompactionLine], cap: int) -> str:
        # Preserve oldest->newest order while strictly enforcing cap.
        out: list[str] = []
        used = 0
        for line in lines:
            text = line.text.strip()
            if not text:
                continue
            add = len(text) + (1 if out else 0)
            if used + add > cap:
                break
            out.append(text)
            used += add
        return "\n".join(out)

    @staticmethod
    def _joined_len(lines: list[CompactionLine]) -> int:
        if not lines:
            return 0
        return sum(len(line.text.strip()) for line in lines if line.text.strip()) + max(0, len(lines) - 1)

    @staticmethod
    def _is_fragment(text: str) -> bool:
        body = text.split(":", 1)[-1].strip() if ":" in text else text.strip()
        return len(body) <= 24 and bool(_FRAGMENT_RE.match(body))
