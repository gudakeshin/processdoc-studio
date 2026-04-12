from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Any


@dataclass(frozen=True)
class DeliverableMetadata:
    output_type: str
    file_extension: str
    mime_type: str
    supports_branding: bool = True
    supports_quality_rubric: bool = True
    requires_rendering: bool = True
    intermediate_format: str = "text"
    skill_output_key: str = ""


class IDeliverable(ABC):
    @abstractmethod
    def get_metadata(self) -> DeliverableMetadata:
        raise NotImplementedError

    @abstractmethod
    def render(self, payload: dict[str, Any], run_dir: Path, branding: Any | None = None) -> Path | None:
        raise NotImplementedError

    def extract_quality_signals(self, artifact_path: Path) -> dict[str, Any]:
        return {"artifact_path": str(artifact_path)}

    def apply_branding(self, payload: dict[str, Any], branding: Any | None = None) -> dict[str, Any]:
        return payload


class DeliverableRegistry:
    _lock = RLock()
    _deliverables: dict[str, IDeliverable] = {}

    @classmethod
    def register(cls, output_type: str, deliverable: IDeliverable) -> None:
        key = str(output_type or "").strip().lower()
        if not key:
            raise ValueError("output_type must be non-empty")
        with cls._lock:
            cls._deliverables[key] = deliverable

    @classmethod
    def get(cls, output_type: str) -> IDeliverable:
        key = str(output_type or "").strip().lower()
        with cls._lock:
            d = cls._deliverables.get(key)
        if d is None:
            raise ValueError(f"Unknown output type: {output_type}")
        return d

    @classmethod
    def all(cls) -> dict[str, IDeliverable]:
        with cls._lock:
            return dict(cls._deliverables)


# ── Auto-register implementations ─────────────────────────────────────────

# Lazy-load deliverable implementations to avoid circular imports
def _init_default_deliverables() -> None:
    """Initialize default deliverable implementations."""
    if DeliverableRegistry._deliverables:
        return  # Already initialized

    try:
        from app.core.deliverable_pptx import PPTXDeliverable
        DeliverableRegistry.register("pptx", PPTXDeliverable())
    except ImportError:
        pass

    try:
        from app.core.deliverable_docx import DOCXDeliverable
        DeliverableRegistry.register("docx", DOCXDeliverable())
    except ImportError:
        pass

    try:
        from app.core.deliverable_pdf import PDFDeliverable
        DeliverableRegistry.register("pdf", PDFDeliverable())
    except ImportError:
        pass

    try:
        from app.core.deliverable_xlsx import XLSXDeliverable
        DeliverableRegistry.register("xlsx", XLSXDeliverable())
    except ImportError:
        pass


# Initialize on module load (but only once)
_init_default_deliverables()
