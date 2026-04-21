"""Compaction trace metadata for digest observability."""

from __future__ import annotations

from dataclasses import dataclass, field


def _default_dropped_sources() -> dict[str, list[str]]:
    return {"wiki_pages": [], "lp_headings": [], "conversation_segments": []}


@dataclass(slots=True)
class CompactionTrace:
    """Records compaction behavior for debugging and API surfacing."""

    tiers_applied: list[str] = field(default_factory=list)
    dropped_sources: dict[str, list[str]] = field(default_factory=_default_dropped_sources)
    original_char_count: int = 0
    final_char_count: int = 0

    def add_tier(self, tier_name: str) -> None:
        if tier_name and tier_name not in self.tiers_applied:
            self.tiers_applied.append(tier_name)

    def drop_source(self, source_type: str, source_id: str) -> None:
        if not source_id:
            return
        bucket = self.dropped_sources.setdefault(source_type, [])
        if source_id not in bucket:
            bucket.append(source_id)

    @property
    def compression_ratio(self) -> float:
        if self.original_char_count <= 0:
            return 1.0
        return round(self.final_char_count / float(self.original_char_count), 4)

    def to_dict(self) -> dict[str, object]:
        return {
            "tiers_applied": list(self.tiers_applied),
            "dropped_sources": {k: list(v) for k, v in self.dropped_sources.items()},
            "original_char_count": int(self.original_char_count),
            "final_char_count": int(self.final_char_count),
            "compression_ratio": self.compression_ratio,
        }
