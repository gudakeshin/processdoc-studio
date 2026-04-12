from __future__ import annotations

from pathlib import Path
from typing import Any

from docx import Document
from docx.shared import RGBColor

from app.core.deliverable import DeliverableMetadata, IDeliverable
from app.core.deliverable_utils import parse_markdown_blocks, safe_text


class DOCXDeliverable(IDeliverable):
    @staticmethod
    def _rgb_tuple(value: str | None) -> tuple[int, int, int]:
        raw = str(value or "").strip().lstrip("#")
        if len(raw) != 6:
            return (0x1A, 0x1A, 0x1A)
        try:
            return (int(raw[0:2], 16), int(raw[2:4], 16), int(raw[4:6], 16))
        except ValueError:
            return (0x1A, 0x1A, 0x1A)

    def get_metadata(self) -> DeliverableMetadata:
        return DeliverableMetadata(
            output_type="docx",
            file_extension=".docx",
            mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            intermediate_format="markdown",
            skill_output_key="docx_markdown",
        )

    def render(self, payload: dict[str, Any], run_dir: Path, branding: Any | None = None) -> Path | None:
        out = run_dir / "output.docx"
        text = safe_text(payload.get("docx_markdown") or payload.get("narrative_md"), "Process document")
        doc = Document()
        title = safe_text((payload.get("process_model") or {}).get("process_name") if isinstance(payload.get("process_model"), dict) else "Process Output", "Process Output")
        font_family = str(getattr(branding, "font_family", "Calibri") or "Calibri")
        primary_rgb = self._rgb_tuple(getattr(branding, "primary_color", None))
        doc.add_heading(title, level=1)
        heading = doc.paragraphs[-1]
        for run in heading.runs:
            run.font.name = font_family
            run.font.color.rgb = RGBColor(*primary_rgb)
        for block in parse_markdown_blocks(text):
            if block["type"] == "heading":
                doc.add_heading(safe_text(block.get("text"), ""), level=min(4, max(1, int(block.get("level", 1)))))
                for run in doc.paragraphs[-1].runs:
                    run.font.name = font_family
                    run.font.color.rgb = RGBColor(*primary_rgb)
            elif block["type"] == "paragraph":
                doc.add_paragraph(safe_text(block.get("text"), ""))
                for run in doc.paragraphs[-1].runs:
                    run.font.name = font_family
            elif block["type"] == "bullets":
                for item in block.get("items", []):
                    doc.add_paragraph(safe_text(item, ""), style="List Bullet")
                    for run in doc.paragraphs[-1].runs:
                        run.font.name = font_family
            elif block["type"] == "table":
                rows = block.get("rows") or []
                if not rows:
                    continue
                cols = max(len(r) for r in rows)
                table = doc.add_table(rows=len(rows), cols=cols)
                table.style = "Table Grid"
                for r_idx, row in enumerate(rows):
                    for c_idx in range(cols):
                        val = row[c_idx] if c_idx < len(row) else ""
                        table.cell(r_idx, c_idx).text = safe_text(val, "")
        doc.save(out)
        return out

    def extract_quality_signals(self, artifact_path: Path) -> dict[str, Any]:
        try:
            doc = Document(str(artifact_path))
            headings = 0
            words = 0
            for p in doc.paragraphs:
                text = (p.text or "").strip()
                if not text:
                    continue
                words += len(text.split())
                style_name = str(getattr(p.style, "name", "") or "").lower()
                if "heading" in style_name:
                    headings += 1
            return {"paragraph_count": len(doc.paragraphs), "word_count": words, "heading_count": headings}
        except Exception:
            return super().extract_quality_signals(artifact_path)

