from __future__ import annotations

from pathlib import Path
from typing import Any

from pypdf import PdfWriter

from app.core.deliverable import DeliverableMetadata, IDeliverable
from app.core.deliverable_utils import parse_markdown_blocks, safe_text


class PDFDeliverable(IDeliverable):
    def get_metadata(self) -> DeliverableMetadata:
        return DeliverableMetadata(
            output_type="pdf",
            file_extension=".pdf",
            mime_type="application/pdf",
            intermediate_format="markdown",
            skill_output_key="pdf_markdown",
        )

    def render(self, payload: dict[str, Any], run_dir: Path, branding: Any | None = None) -> Path | None:
        out = run_dir / "output.pdf"
        summary = safe_text(payload.get("pdf_markdown") or payload.get("narrative_md"), "Generated ProcessDoc PDF output")
        title = safe_text((payload.get("process_model") or {}).get("process_name") if isinstance(payload.get("process_model"), dict) else "Process Output", "Process Output")
        try:
            from reportlab.lib.pagesizes import LETTER
            from reportlab.lib.styles import getSampleStyleSheet
            from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

            doc = SimpleDocTemplate(str(out), pagesize=LETTER, title=title)
            styles = getSampleStyleSheet()
            if branding is not None:
                base_font = str(getattr(branding, "font_family", "") or "").strip()
                if base_font:
                    styles["BodyText"].fontName = base_font
                    styles["Title"].fontName = base_font
            story: list[Any] = [Paragraph(title, styles["Title"]), Spacer(1, 10)]
            for block in parse_markdown_blocks(summary):
                if block["type"] == "heading":
                    story.append(Paragraph(safe_text(block.get("text"), ""), styles["Heading2"]))
                elif block["type"] == "paragraph":
                    story.append(Paragraph(safe_text(block.get("text"), ""), styles["BodyText"]))
                story.append(Spacer(1, 6))
            doc.build(story)
            return out
        except Exception:
            writer = PdfWriter()
            writer.add_blank_page(width=612, height=792)
            writer.add_metadata({"/Title": title, "/Subject": summary[:500]})
            with out.open("wb") as f:
                writer.write(f)
            return out

    def extract_quality_signals(self, artifact_path: Path) -> dict[str, Any]:
        try:
            from pypdf import PdfReader

            reader = PdfReader(str(artifact_path))
            pages = len(reader.pages)
            text_chars = 0
            for p in reader.pages:
                text_chars += len((p.extract_text() or "").strip())
            return {"page_count": pages, "text_chars": text_chars}
        except Exception:
            return super().extract_quality_signals(artifact_path)

