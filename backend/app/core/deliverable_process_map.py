from __future__ import annotations

from pathlib import Path
from typing import Any

from app.core.deliverable import DeliverableMetadata, IDeliverable


class ProcessMapDeliverable(IDeliverable):
    def get_metadata(self) -> DeliverableMetadata:
        return DeliverableMetadata(
            output_type="process_map",
            file_extension=".xml",
            mime_type="application/xml",
            supports_branding=False,
            intermediate_format="xml",
            skill_output_key="drawio_xml",
        )

    def render(self, payload: dict[str, Any], run_dir: Path, branding: Any | None = None) -> Path | None:
        xml = payload.get("drawio_xml")
        if not isinstance(xml, str) or not xml.strip():
            return None
        out = run_dir / "drawio.xml"
        out.write_text(xml, encoding="utf-8")
        mermaid = payload.get("process_map_mermaid")
        if isinstance(mermaid, str) and mermaid.strip():
            (run_dir / "process_map.mmd").write_text(mermaid, encoding="utf-8")
        return out

    def extract_quality_signals(self, artifact_path: Path) -> dict[str, Any]:
        try:
            text = artifact_path.read_text(encoding="utf-8")
        except Exception:
            return super().extract_quality_signals(artifact_path)
        return {
            "xml_chars": len(text),
            "has_mxgraph": "<mxGraphModel" in text or "<mxfile" in text,
        }

