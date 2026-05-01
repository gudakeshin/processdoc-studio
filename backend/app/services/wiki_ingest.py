"""
wiki_ingest.py — Wiki ingestion helpers.

Handles source parsing, page creation/update, index regeneration, and log appending.
"""
import json
import logging
import re
import time as _time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.services.storage import workspace_path

_LOG = logging.getLogger(__name__)
_schema_cache: dict = {}


# ---------------------------------------------------------------------------
# Schema loading
# ---------------------------------------------------------------------------

def _load_wiki_schema(wiki_type: str, project_id) -> str:
    """Load WIKI_SCHEMA.md with a 5-minute in-memory cache."""
    try:
        from app.services.storage import workspace_path
        cache_key = f"{wiki_type}:{project_id}"
        cached = _schema_cache.get(cache_key)
        if cached and (_time.time() - cached[1]) < 300:
            return cached[0]
        if wiki_type == "project":
            wiki_dir = workspace_path(project_id) / "wiki"
        else:
            wiki_dir = Path("leading_practice/wiki")
        schema_path = wiki_dir / "WIKI_SCHEMA.md"
        content = schema_path.read_text() if schema_path.exists() else ""
        _schema_cache[cache_key] = (content, _time.time())
        return content
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Raw source preservation (Karpathy: raw/ layer is immutable)
# ---------------------------------------------------------------------------

def _save_raw_source(wiki_dir: Any, slug: str, content: bytes, ext: str = ".html") -> None:
    """
    Archive raw fetched content into wiki/raw/ before any processing.

    The raw/ directory is treated as immutable — files are never overwritten
    once written, matching Karpathy's principle of preserving original sources.
    """
    try:
        raw_dir = Path(wiki_dir) / "raw"
        raw_dir.mkdir(exist_ok=True)
        dest = raw_dir / f"{slug}{ext}"
        if not dest.exists():
            dest.write_bytes(content)
    except Exception as e:
        _LOG.warning(f"Failed to save raw source {slug}: {e}")


# ---------------------------------------------------------------------------
# Source parsing
# ---------------------------------------------------------------------------

def _parse_source(source_type: str, source_data: dict, project_id: str | None = None) -> dict | None:
    """Parse source and extract key information."""
    try:
        # Handle double-wrapped source_data (frontend sends {source_data: {...}})
        if "source_data" in source_data and len(source_data) == 1:
            source_data = source_data["source_data"]

        _LOG.info(f"[INGEST] _parse_source called: type={source_type}, source_data keys={list(source_data.keys())}")

        if source_type == "url":
            # Fetch and parse URL content
            url = source_data.get("url", "")
            if not url:
                _LOG.warning("URL source missing url field")
                return None

            try:
                from bs4 import BeautifulSoup

                from app.core.config import settings
                from app.services.http_fetch import SafeFetchError, safe_get

                body = safe_get(
                    url,
                    max_bytes=int(getattr(settings, "http_fetch_max_bytes", 2_000_000)),
                    timeout=float(getattr(settings, "http_fetch_timeout_sec", 15.0)),
                )

                # Preserve raw HTML before any processing
                if project_id:
                    try:
                        from app.services.storage import workspace_path as _wp
                        _wiki_dir = _wp(project_id) / "wiki"
                        _raw_slug = re.sub(r"[^a-z0-9_]", "", url.lower().replace("/", "_").replace(".", "_"))[:60]
                        _save_raw_source(_wiki_dir, _raw_slug, body if isinstance(body, bytes) else body.encode())
                    except Exception:  # noqa: S110 — best-effort, non-fatal
                        pass

                # Parse HTML content
                soup = BeautifulSoup(body, "html.parser")

                # Extract title
                title = None
                if soup.find('h1'):
                    title = soup.find('h1').get_text(strip=True)
                elif soup.find('title'):
                    title = soup.find('title').get_text(strip=True)
                else:
                    title = url.split('/')[-1] or "Web Page"

                # Extract main content
                content = ""
                if soup.find('article'):
                    content = soup.find('article').get_text(separator=' ', strip=True)
                elif soup.find('main'):
                    content = soup.find('main').get_text(separator=' ', strip=True)
                else:
                    # Remove script and style elements
                    for script in soup(["script", "style"]):
                        script.decompose()
                    content = soup.get_text(separator=' ', strip=True)

                # Clean up content
                content = ' '.join(content.split())

                if not content:
                    _LOG.warning(f"No content extracted from URL: {url}")
                    return None

                return {
                    "title": title,
                    "content": content,
                    "source_url": url,
                    "chunk_count": max(1, len(content) // 1200),
                    "entities": [],
                    "concepts": [],
                }
            except SafeFetchError as url_err:
                _LOG.error(f"Blocked or invalid URL fetch {url}: {url_err}")
                return None
            except Exception as url_err:
                _LOG.error(f"Error fetching URL {url}: {url_err}")
                return None

        elif source_type == "memory":
            mid = source_data.get("memory_id") or source_data.get("id")
            mtype = source_data.get("memory_type") or source_data.get("type", "fact")
            content = (source_data.get("memory_content") or source_data.get("content") or "").strip()
            meta = source_data.get("metadata") if isinstance(source_data.get("metadata"), dict) else {}
            title = source_data.get("title") or meta.get("title")
            if not title:
                title = f"{mtype}: {content[:60]}" if content else f"memory:{mid or 'unknown'}"
            if not content:
                content = title
            ch = source_data.get("category_hint") or source_data.get("category")
            return {
                "title": title,
                "content": content,
                "source_url": f"memory://{mid}" if mid else "memory://",
                "chunk_count": max(1, len(content) // 1200),
                "entities": [],
                "concepts": [],
                "source_memory_id": str(mid) if mid is not None else "",
                "category_hint": ch if isinstance(ch, str) else None,
            }

        elif source_type == "document":
            # For documents, filename is in source_data; project_id comes from function parameter
            filename = source_data.get("filename", "")
            raw_name = str(filename or "")

            if raw_name and ("\x00" in raw_name or "/" in raw_name or "\\" in raw_name):
                _LOG.error("[INGEST] Rejected unsafe filename characters")
                return None
            filename = Path(raw_name).name
            if not filename or filename in (".", "..") or ".." in Path(raw_name).parts:
                _LOG.error("[INGEST] Rejected unsafe filename")
                return None

            if not filename or not project_id:
                _LOG.error(f"[INGEST] Document ingest FAILED: missing filename or project_id. filename={filename}, project_id={project_id}")
                return None

            _LOG.info(f"[INGEST] Processing document: filename={filename}, project_id={project_id}")

            import hashlib

            from app.services.storage import workspace_path

            source_file = workspace_path(project_id) / "source_docs" / filename

            # Try to read the source file directly as fallback
            if source_file.exists():
                try:
                    content = source_file.read_bytes()
                    digest = hashlib.sha256(content).hexdigest()

                    # First try to get parsed document
                    parsed_docs_dir = workspace_path(project_id) / "parsed_docs"
                    if parsed_docs_dir.exists():
                        parsed_file = parsed_docs_dir / f"{digest}.json"
                        if parsed_file.exists():
                            try:
                                parsed_data = json.loads(parsed_file.read_text())
                                _LOG.debug(f"Using parsed document for {filename}")
                                return {
                                    "title": filename,
                                    "content": parsed_data.get("text", ""),
                                    "source_url": f"document://{project_id}/{filename}",
                                    "content_digest": digest,
                                    "chunk_count": parsed_data.get("chunk_count", 0),
                                    "entities": [],
                                    "concepts": [],
                                }
                            except json.JSONDecodeError as je:
                                _LOG.warning(f"Failed to parse JSON for {filename}: {je}")

                    # Fallback: extract text directly from source file
                    _LOG.debug(f"Using fallback text extraction for {filename}")
                    text = _extract_text_from_file(filename, content)
                    _LOG.info(f"[INGEST] Successfully extracted text from {filename}: length={len(text)}")
                    return {
                        "title": filename,
                        "content": text,
                        "source_url": f"document://{project_id}/{filename}",
                        "content_digest": digest,
                        "chunk_count": max(1, len(text) // 1200),  # Estimate chunks
                        "entities": [],
                        "concepts": [],
                    }
                except Exception as read_err:
                    _LOG.error(f"Error reading source file {filename}: {read_err}")
                    return None
            else:
                from app.services.storage import workspace_path
                source_dir = workspace_path(project_id) / "source_docs"
                available_files = list(source_dir.glob("*")) if source_dir.exists() else []
                _LOG.error(f"[INGEST] Source file NOT FOUND: {source_file}. Available in {source_dir}: {[f.name for f in available_files]}")
                return None

        # For other source types, return basic extracted content
        result = {
            "title": source_data.get("title", "Untitled"),
            "content": source_data.get("content", ""),
            "source_url": source_data.get("url", ""),
            "entities": [],
            "concepts": [],
        }
        _LOG.info(f"[INGEST] _parse_source returning: title={result.get('title')}, content_length={len(result.get('content', ''))}")
        return result
    except Exception as e:
        _LOG.error(f"[INGEST] _parse_source EXCEPTION: {e}")
        return None


def _extract_text_from_file(filename: str, content: bytes) -> str:
    """Extract text from file bytes using proper parsers for each format."""
    try:
        import io
        lower = (filename or "").lower()

        # Text formats
        if lower.endswith((".txt", ".md", ".csv", ".json")):
            return content.decode("utf-8", errors="ignore")

        # DOCX files
        if lower.endswith(".docx"):
            try:
                from docx import Document
                doc = Document(io.BytesIO(content))
                text_parts = [paragraph.text for paragraph in doc.paragraphs if paragraph.text.strip()]
                return "\n".join(text_parts) if text_parts else "[No text content in DOCX]"
            except Exception as docx_err:
                _LOG.warning(f"Failed to parse DOCX {filename}: {docx_err}")
                return "[Unable to extract text from DOCX file]"

        # XLSX files
        if lower.endswith(".xlsx"):
            try:
                from openpyxl import load_workbook
                wb = load_workbook(io.BytesIO(content), data_only=True)
                text_parts = []
                for sheet in wb.sheetnames:
                    ws = wb[sheet]
                    text_parts.append(f"[Sheet: {sheet}]")
                    for row in ws.iter_rows(values_only=True):
                        row_text = " | ".join(str(cell) if cell is not None else "" for cell in row).strip()
                        if row_text:
                            text_parts.append(row_text)
                return "\n".join(text_parts) if text_parts else "[No text content in XLSX]"
            except Exception as xlsx_err:
                _LOG.warning(f"Failed to parse XLSX {filename}: {xlsx_err}")
                return "[Unable to extract text from XLSX file]"

        # PDF files
        if lower.endswith(".pdf"):
            try:
                from pypdf import PdfReader

                reader = PdfReader(io.BytesIO(content))
                max_pages = 50
                if len(reader.pages) > max_pages:
                    _LOG.warning(
                        "PDF %s has %s pages; max %s",
                        filename,
                        len(reader.pages),
                        max_pages,
                    )
                    return f"[PDF rejected: exceeds {max_pages} page limit]"
                text_parts = []
                for page_num, page in enumerate(reader.pages[:max_pages]):
                    page_text = page.extract_text().strip()
                    if page_text:
                        text_parts.append(f"[Page {page_num + 1}]\n{page_text}")
                return "\n".join(text_parts) if text_parts else "[No text content in PDF]"
            except Exception as pdf_err:
                _LOG.warning(f"Failed to parse PDF {filename}: {pdf_err}")
                return "[Unable to extract text from PDF file]"

        # PPTX files
        if lower.endswith(".pptx"):
            try:
                import io
                import re as _re
                import zipfile

                from app.core.config import settings
                from app.core.office.zip_safety import UnsafeZipError, validate_zip_for_read

                zf = zipfile.ZipFile(io.BytesIO(content))
                try:
                    validate_zip_for_read(
                        zf,
                        max_uncompressed_bytes=int(
                            getattr(settings, "zip_max_uncompressed_bytes", 100 * 1024 * 1024)
                        ),
                    )
                except UnsafeZipError as zerr:
                    _LOG.warning("Unsafe PPTX zip %s: %s", filename, zerr)
                    return "[Rejected PPTX archive: failed safety checks]"
                text_parts = []
                for name in sorted(zf.namelist()):
                    if not name.startswith("ppt/") or not name.endswith(".xml"):
                        continue
                    raw = zf.read(name).decode("utf-8", errors="ignore")
                    cleaned = _re.sub(r"<[^>]+>", " ", raw)
                    cleaned = _re.sub(r"\s+", " ", cleaned).strip()
                    if cleaned:
                        text_parts.append(cleaned)
                return "\n".join(text_parts) if text_parts else "[No text content in PPTX]"
            except Exception as pptx_err:
                _LOG.warning(f"Failed to parse PPTX {filename}: {pptx_err}")
                return "[Unable to extract text from PPTX file]"

        # XLS files (legacy Excel)
        if lower.endswith(".xls"):
            try:
                import io

                from openpyxl import load_workbook
                wb = load_workbook(io.BytesIO(content), data_only=True, read_only=True)
                text_parts = []
                for sheet in wb.sheetnames:
                    ws = wb[sheet]
                    text_parts.append(f"[Sheet: {sheet}]")
                    for row in ws.iter_rows(values_only=True):
                        row_text = " | ".join(str(cell) if cell is not None else "" for cell in row).strip()
                        if row_text:
                            text_parts.append(row_text)
                return "\n".join(text_parts) if text_parts else "[No text content in XLS]"
            except Exception:
                try:
                    import xlrd  # type: ignore
                    wb = xlrd.open_workbook(file_contents=content)
                    text_parts = []
                    for sheet in wb.sheets():
                        text_parts.append(f"[Sheet: {sheet.name}]")
                        for row_idx in range(sheet.nrows):
                            row_text = " | ".join(str(sheet.cell_value(row_idx, c)) for c in range(sheet.ncols)).strip()
                            if row_text:
                                text_parts.append(row_text)
                    return "\n".join(text_parts) if text_parts else "[No text content in XLS]"
                except Exception as xls_err:
                    _LOG.warning(f"Failed to parse XLS {filename}: {xls_err}")
                    return "[Unable to extract text from XLS file]"

        # Unknown format - try UTF-8 as last resort
        _LOG.warning(f"Unknown file format {filename}, attempting UTF-8 decode")
        return content.decode("utf-8", errors="ignore")

    except Exception as e:
        _LOG.error(f"Failed to extract text from {filename}: {e}")
        return f"[Error extracting text from {filename}: {str(e)}]"


def _infer_category(extracted: dict) -> str:
    """Infer wiki page category (source type) from source URL and title."""
    source_url = extracted.get("source_url", "")
    title = (extracted.get("title") or "").lower()
    if source_url.startswith("https://") or source_url.startswith("http://"):
        return "reference"
    if source_url.startswith("run://"):
        return "run_artifact"
    if source_url.startswith("conversation://"):
        return "conversation"
    if any(title.endswith(ext) for ext in (".pdf", ".docx", ".xlsx", ".pptx")):
        return "document"
    if any(title.endswith(ext) for ext in (".txt", ".md", ".csv")):
        return "note"
    return "artifact"


def _infer_semantic_type(source_type: str, title: str, content: str) -> str:
    """
    Infer semantic type (Karpathy second brain model) from content characteristics.

    Semantic types:
    - topic: Domain or area of knowledge
    - concept: Fundamental idea or principle
    - resource: External reference (document, link, paper)
    - project: Active work or application
    - process: Repeatable procedure or workflow
    - reference: People, tools, events
    """
    title_lower = (title or "").lower()
    content_lower = (content or "").lower()[:2000]  # Check first 2000 chars

    # Detect topic indicators (broad domains)
    topic_keywords = ["overview", "introduction", "guide to", "introduction to", "primer on",
                      "fundamentals", "basics of", "disciplines", "domain", "framework"]
    if any(kw in title_lower for kw in topic_keywords):
        return "topic"

    # Detect project/process indicators
    project_keywords = ["project", "initiative", "implementation", "workflow", "process",
                        "procedure", "system", "program", "deployment", "rollout"]
    if any(kw in title_lower for kw in project_keywords):
        return "project"

    # Detect reference/resource indicators
    if source_type in ["reference", "document"]:
        reference_keywords = ["document", "specification", "blueprint", "architecture",
                            "chart", "diagram", "map", "plan"]
        if any(kw in title_lower or kw in content_lower for kw in reference_keywords):
            return "resource"

    # Detect concepts (principles, ideas, techniques)
    concept_keywords = ["principle", "concept", "theory", "technique", "method", "pattern",
                       "approach", "model", "framework", "strategy"]
    if any(kw in title_lower for kw in concept_keywords):
        return "concept"

    # Detect pain points, metrics, issues
    if "pain point" in content_lower or "metric" in content_lower or "issue" in content_lower:
        return "concept"

    # Default based on source type
    if source_type == "document" or source_type == "reference":
        return "resource"
    elif source_type == "conversation":
        return "concept"

    return "resource"


def _infer_category_from_semantic_type(semantic_type: str) -> str:
    """
    Map semantic type (Karpathy knowledge model) to category (source type).
    This trusts the LLM's classification of what the entity represents conceptually.

    Categories (source type):
    - artifact: Extracted concept/entity (most flexible)
    - concept: For topic/concept semantic types
    - reference: For resource semantic types
    """
    semantic_type = (semantic_type or "").lower()
    _SEMANTIC_TO_CATEGORY = {
        "topic": "artifact",
        "concept": "artifact",
        "process": "artifact",
        "project": "artifact",
        "resource": "reference",
    }
    return _SEMANTIC_TO_CATEGORY.get(semantic_type, "artifact")


# ---------------------------------------------------------------------------
# Wiki schema
# ---------------------------------------------------------------------------

_WIKI_SCHEMA = """\
# WIKI_SCHEMA.md — Wiki Conventions & Workflows

## Purpose
This wiki is an LLM-maintained knowledge base. The LLM reads sources, writes pages, and
cross-references concepts. You source documents and ask questions; the LLM does the filing.

## Page Types & Categories

### Source Type (category)
How the page entered the wiki:
| Category       | Description                                  |
|----------------|----------------------------------------------|
| `document`     | Ingested PDF, DOCX, XLSX, or TXT files       |
| `reference`    | Pages sourced from web URLs                  |
| `note`         | Plain-text notes and markdown files          |
| `run_artifact` | Outputs from project runs                    |
| `conversation` | Distilled conversation summaries             |
| `artifact`     | General-purpose fallback category            |

### Semantic Type (semantic_type)
What kind of knowledge the page represents (Karpathy second-brain model):
| Type       | Description                                              |
|------------|----------------------------------------------------------|
| `topic`    | Broad domain or area of knowledge (e.g., "Supply Chain") |
| `concept`  | Fundamental idea, principle, or technique                |
| `process`  | Repeatable workflow or procedure                         |
| `project`  | Active work, initiative, or application                  |
| `resource` | Reference material, document, or external item           |

## Frontmatter Fields (required)
```yaml
---
title: "Human-readable page title"
category: "source type (document, reference, etc.)"
semantic_type: "topic | concept | process | project | resource"
confidence: "high | medium | low"
source_count: 1
source_url: "https://... or document://project/file"
last_updated: "ISO-8601 timestamp"
created_at:   "ISO-8601 timestamp"
---
```

## Linking Convention
- Inter-page links: `[[page_id|Human Title]]`
- Leading-practice links: `[[lp://page_id|Title]]`
- Cross-project links: `[[wiki://project_id/page_id|Title]]`

## Ingest Workflow
1. Source is parsed (URL fetched or document extracted).
2. LLM writes a summary page for the source.
3. LLM extracts 3-6 key entities and creates/updates their pages.
4. Relationship graph rebuilt; index.md regenerated.
5. log.md entry appended: `## [date] ingest | Source Title`.

## Query Workflow
1. Question scored against all page titles/content (keyword overlap).
2. Top 5 pages passed to LLM as context.
3. LLM synthesises answer with inline citations `[[page_id|Title]]`.
4. Optionally quality-evaluated; answer can be saved as an `insight` page.

## log.md Format
Each entry: `## [YYYY-MM-DD] operation | Source Title`
Parse with: `grep "^## \\[" log.md | tail -10`
"""


def _migrate_meta_directory(wiki_dir):
    """One-time migration: move JSON state files into wiki/.meta/."""
    meta_dir = Path(wiki_dir) / ".meta"
    meta_dir.mkdir(exist_ok=True)
    old_names = {
        "graph.json": "graph.json",
        "communities.json": "communities.json",
        "god_nodes.json": "god_nodes.json",
        "relationships.json": "relationships.json",
        ".page_manifest.json": "page_manifest.json",
    }
    for old_name, new_name in old_names.items():
        old = Path(wiki_dir) / old_name
        new = meta_dir / new_name
        if old.exists() and not new.exists():
            old.rename(new)


def emit_wiki_change_event(
    wiki_type: str,
    project_id: str | None,
    change_type: str,
    changed_page_ids: list[str],
) -> None:
    """Persist wiki change event for optional async graph rebuild workers."""
    try:
        if not bool(getattr(settings, "wiki_evented_graph_rebuild_enabled", False)):
            return
        if wiki_type == "leading_practice":
            wiki_dir = workspace_path("leading_practices") / "wiki"
        else:
            wiki_dir = workspace_path(project_id) / "wiki"
        meta_dir = wiki_dir / ".meta"
        meta_dir.mkdir(parents=True, exist_ok=True)
        events_file = meta_dir / "wiki_rebuild_events.jsonl"
        event = {
            "schema_version": 1,
            "event_type": "wiki_pages_changed",
            "change_type": change_type,
            "wiki_type": wiki_type,
            "project_id": project_id,
            "changed_page_ids": sorted(set(changed_page_ids or [])),
            "created_at": datetime.now(UTC).isoformat(),
        }
        with events_file.open("a", encoding="utf-8") as fp:
            fp.write(json.dumps(event) + "\n")
    except Exception as exc:
        _LOG.warning("Failed to emit wiki change event: %s", exc)


def _ensure_wiki_schema(wiki_dir: Any) -> None:
    """Write WIKI_SCHEMA.md on first use of a wiki directory."""
    _migrate_meta_directory(wiki_dir)
    schema_file = wiki_dir / "WIKI_SCHEMA.md"
    if not schema_file.exists():
        schema_file.write_text(_WIKI_SCHEMA)


def _make_frontmatter(fields: dict) -> str:
    """Render a YAML frontmatter block."""
    lines = ["---"]
    for key, value in fields.items():
        if isinstance(value, str):
            lines.append(f'{key}: "{value}"')
        else:
            lines.append(f"{key}: {value}")
    lines.append("---\n")
    return "\n".join(lines)


def _read_frontmatter_field(page_file: Path, field: str) -> str | None:
    """Read a single string field from a page's YAML frontmatter."""
    try:
        if not page_file.exists():
            return None
        text = page_file.read_text(encoding="utf-8")
        fm = re.match(r"^---\n(.*?)\n---", text, re.DOTALL)
        if not fm:
            return None
        for line in fm.group(1).splitlines():
            stripped = line.strip()
            if stripped.startswith(f"{field}:"):
                value = stripped.split(":", 1)[1].strip()
                return value.strip('"').strip("'")
    except Exception:
        return None
    return None


# ---------------------------------------------------------------------------
# Backlink weaving
# ---------------------------------------------------------------------------

def _weave_backlinks(wiki_dir: Any, new_page_ids: list, new_page_titles: dict) -> int:
    """
    Scan every wiki page for plain-text mentions of newly created/updated page
    titles and replace first occurrence with a [[page_id|Title]] wiki-link.

    Returns the number of pages that received at least one new backlink.
    """
    if not new_page_titles:
        return 0
    woven = 0
    try:
        for md_file in sorted(Path(wiki_dir).glob("*.md")):
            if md_file.name in ("index.md", "log.md", "WIKI_SCHEMA.md"):
                continue
            try:
                text = md_file.read_text(encoding="utf-8")
                changed = False
                for page_id, title in new_page_titles.items():
                    if md_file.stem == page_id:
                        continue  # skip self-links
                    wiki_link = f"[[{page_id}|{title}]]"
                    if wiki_link in text:
                        continue  # already linked
                    # Match bare title not already inside [[ ]]
                    pattern = rf"(?<!\[\[)(?<!\|)\b{re.escape(title)}\b(?!\]\])"
                    if re.search(pattern, text):
                        text = re.sub(pattern, wiki_link, text, count=1)
                        changed = True
                if changed:
                    md_file.write_text(text, encoding="utf-8")
                    woven += 1
            except Exception:  # noqa: S112 — best-effort, non-fatal
                continue
    except Exception as e:
        _LOG.warning(f"Backlink weaving failed: {e}")
    return woven


def _weave_entity_backlinks(wiki_dir: Any, entities: list) -> int:
    """
    Scan wiki pages for mentions of extracted entities and link them.

    Entities are turned into hub nodes: all mentions across the wiki get linked
    to their entity pages, creating a knowledge graph where entities connect related pages.

    Args:
        wiki_dir: Path to wiki directory
        entities: List of dicts with keys: name (entity name), page_id (entity page id)

    Returns:
        Number of pages modified
    """
    if not entities:
        return 0

    # Build map of entity names → page_ids, filter out short/common terms
    entity_map = {}
    for entity in entities:
        name = (entity.get("name") or "").strip()
        page_id = entity.get("page_id", "").strip()
        if name and page_id and len(name) > 2:  # Skip very short terms
            entity_map[name] = page_id

    if not entity_map:
        return 0

    woven = 0
    try:
        for md_file in sorted(Path(wiki_dir).glob("*.md")):
            if md_file.name in ("index.md", "log.md", "WIKI_SCHEMA.md"):
                continue
            try:
                text = md_file.read_text(encoding="utf-8")
                changed = False

                for entity_name, page_id in entity_map.items():
                    if md_file.stem == page_id:
                        continue  # skip self-links

                    wiki_link = f"[[{page_id}|{entity_name}]]"
                    if wiki_link in text:
                        continue  # already linked

                    # Match bare entity name (case-insensitive) not already inside [[ ]]
                    # For multi-word entities, use looser word boundaries
                    pattern = rf"(?<!\[\[)(?<!\|)(?<!\w){re.escape(entity_name)}(?!\w)(?!\]\])"
                    if re.search(pattern, text, re.IGNORECASE):
                        # Replace only first occurrence per entity per page
                        text = re.sub(pattern, wiki_link, text, count=1, flags=re.IGNORECASE)
                        changed = True

                if changed:
                    md_file.write_text(text, encoding="utf-8")
                    woven += 1

            except Exception:  # noqa: S112 — best-effort, non-fatal
                continue

    except Exception as e:
        _LOG.warning(f"Entity backlink weaving failed: {e}")

    return woven


# ---------------------------------------------------------------------------
# Compounding entity page update
# ---------------------------------------------------------------------------

def _compound_update_entity_page(
    efile: Any,
    ename: str,
    esummary: str,
    source_title: str,
    page_id: str,
) -> None:
    """
    Rewrite an existing entity page by asking Claude to integrate old knowledge
    with new information from the current source.  Falls back to appending a
    section when Claude is unavailable.
    """
    try:
        existing_text = efile.read_text(encoding="utf-8")
        # Strip frontmatter for the LLM, restore it afterwards
        fm_match = re.match(r"(^---\n.*?\n---\n?)(.*)", existing_text, re.DOTALL)
        frontmatter = fm_match.group(1) if fm_match else ""
        existing_body = fm_match.group(2).strip() if fm_match else existing_text.strip()

        # Update last_updated timestamp in frontmatter
        now = datetime.now(UTC).isoformat()
        frontmatter = re.sub(r'last_updated:\s*"[^"]*"', f'last_updated: "{now}"', frontmatter)
        if "last_updated" not in frontmatter and frontmatter:
            frontmatter = frontmatter.removesuffix("---\n") + f'\nlast_updated: "{now}"\n---\n'

        try:
            from app.services.claude import claude_generate, is_claude_enabled
            if not is_claude_enabled():
                raise RuntimeError("Claude disabled")

            updated_body = claude_generate(
                system=(
                    "You are a wiki curator following Karpathy's second-brain model. "
                    "You are updating an existing entity page with new information from a source. "
                    "Extract and retain high-signal source facts instead of over-paraphrasing. "
                    "When adding quantitative or specific claims, include a short source locator "
                    "like '(source: [[page_id|Title]])'. "
                    "Rewrite the page body in Markdown to:\n"
                    "1. Integrate the new information naturally (don't just append)\n"
                    "2. Flag any contradictions with a '> ⚠️ Contradicts:' blockquote\n"
                    "3. Add a '## Sources' section at the bottom listing source back-references using [[page_id|Title]] links\n"
                    "4. Preserve all existing [[wiki-link]] references\n"
                    "Do NOT include YAML frontmatter — start directly with the page heading."
                ),
                user=(
                    f"Entity: {ename}\n\n"
                    f"Existing page content:\n{existing_body[:1200]}\n\n"
                    f"New information from [[{page_id}|{source_title}]]:\n{esummary}"
                ),
                max_tokens=900,
            )
            efile.write_text(frontmatter + updated_body, encoding="utf-8")
        except Exception:
            # Fallback: structured append
            append = (
                f"\n\n### From [[{page_id}|{source_title}]]\n\n{esummary}\n"
            )
            efile.write_text(existing_text + append, encoding="utf-8")
    except Exception as e:
        _LOG.warning(f"Compound update failed for {efile}: {e}")


# ---------------------------------------------------------------------------
# Entity deduplication
# ---------------------------------------------------------------------------

def _is_duplicate_entity(name: str, existing_titles: list, threshold: float = 0.5) -> bool:
    """Return True if name is similar enough to an existing page title to skip creation."""
    import re as _re
    a = set(_re.findall(r"\w+", name.lower()))
    for title in existing_titles:
        b = set(_re.findall(r"\w+", title.lower()))
        if a and b and len(a & b) / len(a | b) >= threshold:
            return True
    return False


# ---------------------------------------------------------------------------
# Page creation/update
# ---------------------------------------------------------------------------

def _update_wiki_pages(extracted: dict, wiki_type: str, project_id: str | None) -> dict:
    """Create/update wiki pages using LLM to synthesize content and extract entities."""
    try:
        if not extracted or not extracted.get("content"):
            _LOG.error(f"[INGEST] _update_wiki_pages received empty extracted content. extracted={extracted}")
            return {"created": 0, "updated": 0, "page_ids": [], "corrections": []}

        from app.services.claude import claude_generate_json, is_claude_enabled
        from app.services.storage import workspace_path

        if wiki_type == "leading_practice":
            wiki_dir = workspace_path("leading_practices") / "wiki"
        else:
            wiki_dir = workspace_path(project_id) / "wiki"

        wiki_dir.mkdir(parents=True, exist_ok=True)
        _ensure_wiki_schema(wiki_dir)

        source_title = extracted.get("title", "Document")
        source_url = extracted.get("source_url", "")
        content_digest = extracted.get("content_digest", "")
        content_preview = extracted.get("content", "")[:3000]

        # Short-circuit: if a main page for this source_url already exists with the
        # same content_digest, the document is unchanged. Skip LLM and entity work.
        candidate_main_id = re.sub(r"[^a-z0-9_]", "", source_title.lower().replace(" ", "_"))[:50]
        candidate_main_file = wiki_dir / f"{candidate_main_id}.md"
        if (
            content_digest
            and candidate_main_file.exists()
            and _read_frontmatter_field(candidate_main_file, "content_digest") == content_digest
            and _read_frontmatter_field(candidate_main_file, "source_url") == source_url
        ):
            _LOG.info(f"[INGEST] Skipping unchanged source: {source_title} (digest match)")
            return {
                "created": 0,
                "updated": 0,
                "page_ids": [candidate_main_id],
                "corrections": [],
                "skipped_unchanged": True,
            }

        existing_pages = [f.stem for f in wiki_dir.glob("*.md")
                          if f.name not in ("index.md", "log.md")]
        existing_titles = existing_pages  # stems used as titles for dedup

        # --- LLM synthesis ---
        page_summary = content_preview[:600]
        entities: list = []
        related_pages: list[dict[str, str]] = []

        if is_claude_enabled():
            try:
                # Load schema for injection
                schema = _load_wiki_schema(wiki_type, project_id)
                schema_prefix = f"Wiki schema and conventions:\n{schema}\n\n" if schema else ""

                existing_refs = []
                for pid in existing_pages:
                    pfile = wiki_dir / f"{pid}.md"
                    title = pid
                    if pfile.exists():
                        fm = re.match(r"^---\n(.*?)\n---", pfile.read_text(), re.DOTALL)
                        if fm:
                            for line in fm.group(1).split("\n"):
                                if line.startswith("title:"):
                                    title = line.split(":", 1)[1].strip().strip('"')
                                    break
                    existing_refs.append({"page_id": pid, "title": title})
                entity_system = (
                    schema_prefix
                    + "You are a wiki maintainer following the second-brain knowledge structure.\n"
                    + "Extract, do not paraphrase aggressively: preserve critical facts as close to source wording as possible.\n"
                    + "Use inline wiki-links in summary text whenever a known page should be referenced.\n"
                    + "Given source content, return JSON with:\n"
                    "{\n"
                    '  "page_summary": "2-4 paragraph wiki summary using inline [[page_id|Title]] links where relevant",\n'
                    '  "entities": [\n'
                    '    {"name": "Entity Name", "semantic_type": "topic|concept|process|resource", "summary": "2-3 sentences"}\n'
                    "  ],\n"
                    '  "related_pages": [\n'
                    '    {"page_id": "existing_page_id", "relation_type": "references|mentions|related_to", "rationale": "one sentence"}\n'
                    "  ]\n"
                    "}\n"
                    "Extract 3-5 key knowledge entities worth their own wiki entries. Use semantic types:\n"
                    "- topic: Broad domain or area of knowledge (e.g., 'Procurement', 'Supply Chain')\n"
                    "- concept: Fundamental idea, principle, or technique (e.g., '3-way matching', 'Vendor management')\n"
                    "- process: Repeatable workflow or procedure (e.g., 'Invoice processing', 'Purchase order workflow')\n"
                    "- resource: Reference materials, documents, or external items\n"
                    "\n"
                    "CRITICAL — Do NOT extract individual person names. Examples of what to SKIP:\n"
                    "- Personal names: 'John Smith', 'Hemant Joshi', 'Rajesh Mehta', 'Tarang Jain' (individual humans)\n"
                    "- CEO/CFO + name: 'CFO John Smith', 'VP Alice Johnson' — extract only the role, not the person\n"
                    "\n"
                    "Extract people ONLY if they have a distinct concept or process identity:\n"
                    "- 'CFO role' (the role concept), not 'CFO John Smith'\n"
                    "- 'founder-led model' (the process), not 'Elon Musk'\n"
                    "- 'procurement team' (the group), not 'John + Mary + Ahmed'\n"
                    "\n"
                    "Only propose new entities not already covered by existing pages. "
                    f"Existing pages: {json.dumps(existing_refs)}\n"
                    "Return strict JSON only."
                )

                llm_result = claude_generate_json(
                    system=entity_system,
                    user=(
                        f"Source title: {source_title}\n"
                        f"Source URL/path: {source_url}\n\n"
                        f"Content:\n{content_preview}\n\n"
                        f"Existing wiki pages: {existing_titles}"
                    ),
                    max_tokens=1500,
                )
                page_summary = llm_result.get("page_summary", page_summary)
                entities = llm_result.get("entities", [])
                related_pages = llm_result.get("related_pages", [])
            except Exception as llm_err:
                _LOG.warning(f"LLM synthesis failed, falling back to excerpt: {llm_err}")

        now = datetime.now(UTC).isoformat()
        created = 0
        updated = 0
        page_ids = []

        # --- Main source page (frontmatter prepared now, body written after entity resolution) ---
        page_id = re.sub(r"[^a-z0-9_]", "", source_title.lower().replace(" ", "_"))[:50]
        page_file = wiki_dir / f"{page_id}.md"
        is_update = page_file.exists()

        source_category = _infer_category(extracted)
        semantic_type = _infer_semantic_type(source_category, source_title, extracted.get("content", ""))

        # --- Entity pages (up to 3) ---
        # Track every (entity_name, real_page_id) we touched, so we can build a
        # "## Related concepts" section on the parent and rewrite LLM slug guesses.
        related_entity_links: list[tuple[str, str]] = []  # (page_id, display_name)
        for entity in entities[:3]:
            ename = (entity.get("name") or "").strip()
            esummary = (entity.get("summary") or "").strip()
            if not ename or not esummary:
                continue

            # Dedup check: if similar to existing, compound-update instead of creating
            if _is_duplicate_entity(ename, existing_titles):
                import re as _re
                a = set(_re.findall(r"\w+", ename.lower()))
                best_match = None
                best_score = 0.0
                for title in existing_titles:
                    b = set(_re.findall(r"\w+", title.lower()))
                    if a and b:
                        score = len(a & b) / len(a | b)
                        if score > best_score:
                            best_score = score
                            best_match = title
                if best_match:
                    efile = wiki_dir / f"{best_match}.md"
                    if efile.exists():
                        _compound_update_entity_page(efile, ename, esummary, source_title, page_id)
                        updated += 1
                        page_ids.append(best_match)
                        related_entity_links.append((best_match, ename))
                continue

            eid = re.sub(r"[^a-z0-9_]", "", ename.lower().replace(" ", "_"))[:50]
            efile = wiki_dir / f"{eid}.md"

            if efile.exists():
                # Compound-update: Claude integrates existing knowledge with new information
                _compound_update_entity_page(efile, ename, esummary, source_title, page_id)
                updated += 1
            else:
                entity_semantic_type = entity.get("semantic_type", "concept")
                # Inherit category from the parent source so new entity pages aren't orphaned
                # under "unclassified". They also persist a source_url back to the parent doc.
                efm = _make_frontmatter({
                    "title": ename,
                    "category": source_category,
                    "semantic_type": entity_semantic_type,
                    "confidence": "medium",
                    "source_count": 1,
                    "source_url": source_url,
                    "source_pages": f"[{page_id}]",
                    "last_updated": now,
                    "created_at": now,
                })
                efile.write_text(f"{efm}\n# {ename}\n\n{esummary}\n")
                created += 1
            page_ids.append(eid)
            related_entity_links.append((eid, ename))

        # --- Rewrite LLM-invented slugs in page_summary to real page_ids ---
        # The LLM emits [[guessed_slug|Display]] but its slug rarely matches our slugger.
        # Map by display title (case-insensitive) onto: created entities, then existing pages.
        title_to_id: dict[str, str] = {}
        for eid, ename in related_entity_links:
            title_to_id[ename.lower()] = eid
        for pid in existing_pages:
            pfile = wiki_dir / f"{pid}.md"
            t = _read_frontmatter_field(pfile, "title") if pfile.exists() else None
            if t:
                title_to_id.setdefault(t.lower(), pid)
            title_to_id.setdefault(pid.lower(), pid)

        def _fix_link(m: re.Match) -> str:
            display = m.group(2).strip()
            real = title_to_id.get(display.lower())
            if real:
                return f"[[{real}|{display}]]"
            # Drop unresolved links to plain text so the page doesn't render dead [[…]] chips
            return display

        page_summary = re.sub(r"\[\[([^\[\]\|]+)\|([^\[\]]+)\]\]", _fix_link, page_summary)

        # --- Build the source page body, including a Related concepts section ---
        related_section = ""
        if related_entity_links:
            bullets = "\n".join(f"- [[{eid}|{name}]]" for eid, name in related_entity_links)
            related_section = f"\n\n## Related concepts\n\n{bullets}\n"

        fm = _make_frontmatter({
            "title": source_title,
            "category": source_category,
            "semantic_type": semantic_type,
            "confidence": "medium",
            "source_count": 1,
            "source_url": source_url,
            "content_digest": content_digest,
            "last_updated": now,
            **({"created_at": now} if not is_update else {}),
        })
        page_body = f"# {source_title}\n\n{page_summary}{related_section}"
        page_text = f"{fm}\n{page_body}\n"
        if is_update and _is_user_edited_page(page_file):
            _compound_update_entity_page(page_file, source_title, page_summary, source_title, page_id)
        else:
            page_file.write_text(page_text)
        _annotate_contradictions(page_file, source_title, related_pages)
        page_ids.insert(0, page_id)

        if is_update:
            updated += 1
        else:
            created += 1

        # Weave backlinks: replace bare title mentions with [[page_id|Title]] links
        new_titles = {}
        for pid in page_ids:
            pfile = wiki_dir / f"{pid}.md"
            if pfile.exists():
                fm = re.match(r"^---\n(.*?)\n---", pfile.read_text(), re.DOTALL)
                if fm:
                    for line in fm.group(1).split("\n"):
                        if line.startswith("title:"):
                            new_titles[pid] = line.split(":", 1)[1].strip().strip('"')
                            break
                if pid not in new_titles:
                    new_titles[pid] = pid
        woven = _weave_backlinks(wiki_dir, page_ids, new_titles)
        _LOG.info(f"Backlinks woven into {woven} pages")

        # Weave entity backlinks: link all mentions of extracted entities
        # This turns entities into hub nodes connecting related pages
        entity_links = []
        for entity in entities[:3]:
            ename = (entity.get("name") or "").strip()
            if ename:
                eid = re.sub(r"[^a-z0-9_]", "", ename.lower().replace(" ", "_"))[:50]
                entity_links.append({"name": ename, "page_id": eid})

        if entity_links:
            entity_woven = _weave_entity_backlinks(wiki_dir, entity_links)
            _LOG.info(f"Entity backlinks woven into {entity_woven} pages")

        from app.services.wiki_graph import _build_and_persist_relationships
        _build_and_persist_relationships(wiki_type, project_id)
        if related_pages:
            _persist_related_page_suggestions(wiki_type, project_id, page_id, related_pages)
        _update_wiki_index(wiki_type, project_id)

        # Analyze graph structure to flag anomalous pages (Karpathy approach: let structure reveal issues)
        anomalies = _detect_anomalous_pages(wiki_type, project_id, page_ids)

        _LOG.info(f"Wiki updated: {created} created, {updated} updated, pages={page_ids}, anomalies={len(anomalies)}")
        emit_wiki_change_event(
            wiki_type=wiki_type,
            project_id=project_id,
            change_type="page_set_changed",
            changed_page_ids=page_ids,
        )
        return {"created": created, "updated": updated, "page_ids": page_ids, "corrections": anomalies}

    except Exception as e:
        _LOG.error(f"Error updating wiki pages: {e}")
        return {"created": 0, "updated": 0, "page_ids": [], "corrections": []}


def _persist_related_page_suggestions(
    wiki_type: str,
    project_id: str | None,
    source_page_id: str,
    related_pages: list[dict[str, str]],
) -> None:
    """Persist LLM-provided related pages into relationships storage."""
    try:
        if wiki_type == "leading_practice":
            wiki_dir = workspace_path("leading_practices") / "wiki"
        else:
            wiki_dir = workspace_path(project_id) / "wiki"

        meta_dir = wiki_dir / ".meta"
        meta_dir.mkdir(exist_ok=True)
        rel_file = meta_dir / "relationships.json"
        schema_version = 2
        if rel_file.exists():
            data = json.loads(rel_file.read_text(encoding="utf-8"))
            if "data" in data and isinstance(data.get("data"), dict):
                schema_version = int(data.get("schema_version", schema_version) or schema_version)
                data = data["data"]
        else:
            data = {"relationships": [], "total": 0}

        relationships = data.get("relationships", [])
        existing_pairs = {(r.get("source_id"), r.get("target_id")) for r in relationships}
        now = datetime.now(UTC).isoformat()
        for rel in related_pages:
            target_id = str(rel.get("page_id") or "").strip()
            if not target_id or target_id == source_page_id:
                continue
            pair = (source_page_id, target_id)
            if pair in existing_pairs:
                continue
            relationships.append({
                "source_id": source_page_id,
                "target_id": target_id,
                "relation_type": rel.get("relation_type", "related_to"),
                "confidence": "LLM",
                "confidence_score": 0.75,
                "source_location": "llm_related_pages",
                "rationale": rel.get("rationale", ""),
                "created_at": now,
            })
            existing_pairs.add(pair)

        data["relationships"] = relationships
        data["total"] = len(relationships)
        data["last_updated"] = now
        if bool(getattr(settings, "wiki_meta_schema_versioning_enabled", True)):
            payload = {"schema_version": schema_version, "data": data}
        else:
            payload = data
        rel_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except Exception as exc:
        _LOG.warning("Persisting related page suggestions failed: %s", exc)


def _annotate_contradictions(page_file: Path, source_title: str, related_pages: list[dict[str, str]]) -> None:
    """Add visible contradiction annotations to page content."""
    try:
        contradictions = []
        for rel in related_pages:
            relation_type = str(rel.get("relation_type", "")).strip().lower()
            rationale = str(rel.get("rationale", "")).strip()
            if relation_type == "contradicts" or "contradict" in rationale.lower():
                page_id = str(rel.get("page_id", "")).strip()
                if not page_id:
                    continue
                contradictions.append((page_id, rationale))

        if not contradictions:
            return

        content = page_file.read_text(encoding="utf-8")
        blocks = []
        for page_id, rationale in contradictions:
            msg = rationale or "Potential conflict detected during ingest."
            blocks.append(f"> ⚠️ Contradicts: [[{page_id}|{page_id}]] — {msg}")
        annotation = "\n".join(blocks)
        if annotation in content:
            return
        updated = f"{content.rstrip()}\n\n## Contradictions\n{annotation}\n"
        page_file.write_text(updated, encoding="utf-8")
        _LOG.info("Added contradiction annotations for %s", source_title)
    except Exception as exc:
        _LOG.warning("Contradiction annotation failed for %s: %s", source_title, exc)


def _is_user_edited_page(page_file: Path) -> bool:
    """Check whether page frontmatter has been marked as user-edited."""
    try:
        if not page_file.exists():
            return False
        text = page_file.read_text(encoding="utf-8")
        fm = re.match(r"^---\n(.*?)\n---", text, re.DOTALL)
        if not fm:
            return False
        for line in fm.group(1).splitlines():
            if line.strip().startswith("user_edited:"):
                value = line.split(":", 1)[1].strip().lower()
                return value in {"true", '"true"', "'true'"}
    except Exception:
        return False
    return False


# ---------------------------------------------------------------------------
# Anomaly detection (Karpathy Second Brain approach)
# ---------------------------------------------------------------------------

def _detect_anomalous_pages(wiki_type: str, project_id: str | None, recently_created_ids: list) -> list:
    """
    Detect anomalous pages using graph structure analysis (Karpathy Second Brain approach).

    In Karpathy's model, a page's category and identity should emerge from its connections,
    not be pre-assigned. Isolated or orphaned pages reveal themselves as anomalies.

    This function flags:
    - Orphaned pages (no relationships) — the graph reveals they're disconnected
    - Capitalized two-word names with zero connections — likely person names, not concepts
    - Pages whose connectivity pattern doesn't match their semantic_type

    Returns list of corrections (flags for manual review):
    {"page_id": "...", "issue": "...", "severity": "...", "description": "...", "suggestion": "..."}
    """
    try:
        from app.services.storage import workspace_path

        if wiki_type == "leading_practice":
            wiki_dir = workspace_path("leading_practices") / "wiki"
        else:
            wiki_dir = workspace_path(project_id) / "wiki"

        # Load relationship graph
        meta_dir = wiki_dir / ".meta"
        relationships_file = meta_dir / "relationships.json"

        if not relationships_file.exists():
            return []

        relationships = json.loads(relationships_file.read_text())
        anomalies = []

        # Analyze recently created pages for structural anomalies
        for page_id in recently_created_ids:
            page_file = wiki_dir / f"{page_id}.md"
            if not page_file.exists():
                continue

            # Read page metadata
            content = page_file.read_text()
            title_match = re.search(r'title:\s*"([^"]+)"', content)
            title = title_match.group(1) if title_match else page_id

            semantic_match = re.search(r'semantic_type:\s*"([^"]+)"', content)
            semantic_type = semantic_match.group(1) if semantic_match else "unknown"

            # Check if page is orphaned in the graph
            page_relationships = relationships.get(page_id, {})
            incoming = len(page_relationships.get("incoming", []))
            outgoing = len(page_relationships.get("outgoing", []))
            total_connections = incoming + outgoing

            # RED FLAG: Completely orphaned pages
            if total_connections == 0:
                # Pattern match: Capitalized Two-Word Name + orphaned = likely person name
                words = title.split()
                is_person_pattern = (
                    len(words) == 2 and
                    all(w[0].isupper() and len(w) >= 2 for w in words if w)
                )

                if is_person_pattern:
                    anomalies.append({
                        "page_id": page_id,
                        "title": title,
                        "issue": "orphaned_person_name_pattern",
                        "severity": "high",
                        "description": f"Page '{title}' is completely isolated (0 relationships) and matches person name pattern (CapitalizedWord CapitalizedWord). Likely a person name extracted as a '{semantic_type}'.",
                        "suggestion": f"REVIEW: Is '{title}' a person name? If yes, delete this page. If it's a genuine concept, it needs to be linked to related knowledge.",
                        "graph_stats": {"incoming": incoming, "outgoing": outgoing}
                    })
                else:
                    anomalies.append({
                        "page_id": page_id,
                        "title": title,
                        "issue": "orphaned_page",
                        "severity": "medium",
                        "description": f"Page '{title}' (semantic_type: {semantic_type}) has 0 relationships in the knowledge graph—completely disconnected.",
                        "suggestion": "Review: Is this a legitimate concept that should be connected, or should it be merged/deleted?",
                        "graph_stats": {"incoming": incoming, "outgoing": outgoing}
                    })

            # YELLOW FLAG: Very low connectivity (1 relationship = likely just back-reference to source)
            elif total_connections == 1 and incoming == 1 and outgoing == 0:
                # Only has an incoming link from source, no other connections
                anomalies.append({
                    "page_id": page_id,
                    "title": title,
                    "issue": "weakly_connected",
                    "severity": "low",
                    "description": f"Page '{title}' (semantic_type: {semantic_type}) has only 1 connection (back to source), no other graph presence.",
                    "suggestion": "Consider if this should be merged with existing concepts or if important relationships are missing.",
                    "graph_stats": {"incoming": incoming, "outgoing": outgoing}
                })

        return anomalies

    except Exception as e:
        _LOG.warning(f"Error detecting anomalous pages: {e}")
        return []


# ---------------------------------------------------------------------------
# Index regeneration
# ---------------------------------------------------------------------------

def _update_wiki_index(wiki_type: str, project_id: str | None) -> dict:
    """
    Regenerate wiki index as a two-tier hierarchical catalog.

    Tier 1 — "Start Here": topics → concepts → processes (the knowledge spine)
    Tier 2 — Full catalog grouped by category with one-line summaries

    Follows Karpathy's principle: the index should let an LLM navigate at scale
    via summaries rather than brute-force reading every page.
    """
    try:
        from app.services.storage import workspace_path

        if wiki_type == "leading_practice":
            wiki_dir = workspace_path("leading_practices") / "wiki"
        else:
            wiki_dir = workspace_path(project_id) / "wiki"

        if not wiki_dir.exists():
            return {"page_count": 0}

        by_category: dict[str, list] = {}
        by_semantic: dict[str, list] = {}

        for md_file in sorted(wiki_dir.glob("*.md")):
            if md_file.name in ("index.md", "log.md", "WIKI_SCHEMA.md"):
                continue
            try:
                content = md_file.read_text(encoding="utf-8")
                title = md_file.stem
                category = "artifact"
                semantic_type = "resource"

                fm_match = re.match(r"^---\n(.*?)\n---", content, re.DOTALL)
                if fm_match:
                    for line in fm_match.group(1).split("\n"):
                        if ":" in line:
                            k, v = line.split(":", 1)
                            k, v = k.strip(), v.strip().strip('"')
                            if k == "title":
                                title = v
                            elif k == "category":
                                category = v
                            elif k == "semantic_type":
                                semantic_type = v

                body = re.sub(r"^---\n.*?\n---\n?", "", content, flags=re.DOTALL)
                body = re.sub(r"^\s*#[^\n]*\n?", "", body, flags=re.MULTILINE).strip()
                first_line = next((ln.strip() for ln in body.splitlines() if ln.strip()), "")
                summary = (first_line[:120] + "…") if len(first_line) > 120 else first_line

                entry = {"id": md_file.stem, "title": title, "summary": summary}
                by_category.setdefault(category, []).append(entry)
                by_semantic.setdefault(semantic_type, []).append(entry)
            except Exception:  # noqa: S112 — best-effort, non-fatal
                continue

        total = sum(len(v) for v in by_category.values())
        date_str = datetime.now(UTC).strftime("%Y-%m-%d")

        lines = [
            "# Wiki Index",
            "",
            f"*{total} pages · updated {date_str}*",
            "",
            "---",
            "",
            "## Start Here",
            "",
            "_Read in this order to build a complete mental model of the domain._",
            "",
        ]

        # Tier 1: knowledge spine — topic → concept → process → project → resource
        spine_order = ["topic", "concept", "process", "project", "resource", "synthesis"]
        spine_labels = {
            "topic": "Topics (broad domains)",
            "concept": "Concepts (ideas & principles)",
            "process": "Processes (workflows & procedures)",
            "project": "Projects (active work)",
            "resource": "Resources (reference material)",
            "synthesis": "Synthesis (cross-cutting insights)",
        }
        for stype in spine_order:
            pages = sorted(by_semantic.get(stype, []), key=lambda p: p["title"].lower())
            if not pages:
                continue
            lines.append(f"### {spine_labels.get(stype, stype.title())} ({len(pages)})")
            lines.append("")
            for p in pages:
                suffix = f" — {p['summary']}" if p["summary"] else ""
                lines.append(f"- [[{p['id']}|{p['title']}]]{suffix}")
            lines.append("")

        # Tier 2: full catalog by source category
        lines += ["---", "", "## Full Catalog (by source)", ""]
        for cat in sorted(by_category):
            pages = sorted(by_category[cat], key=lambda p: p["title"].lower())
            label = cat.replace("_", " ").title()
            lines.append(f"### {label} ({len(pages)})")
            lines.append("")
            for p in pages:
                suffix = f" — {p['summary']}" if p["summary"] else ""
                lines.append(f"- [[{p['id']}|{p['title']}]]{suffix}")
            lines.append("")

        (wiki_dir / "index.md").write_text("\n".join(lines))
        return {"page_count": total}

    except Exception as e:
        _LOG.error(f"Error updating wiki index: {e}")
        return {"page_count": 0}


# ---------------------------------------------------------------------------
# Log
# ---------------------------------------------------------------------------

def _append_wiki_log(
    wiki_type: str,
    project_id: str | None,
    operation: str,
    source_name: str | None = None,
    pages_touched: list | None = None,
    corrections_made: list | None = None,
    qa_results: str | None = None,
) -> str:
    """Append operation to wiki log."""
    try:
        from app.services.storage import workspace_path

        if wiki_type == "leading_practice":
            wiki_dir = workspace_path("leading_practices") / "wiki"
        else:
            wiki_dir = workspace_path(project_id) / "wiki"

        wiki_dir.mkdir(parents=True, exist_ok=True)
        log_file = wiki_dir / "log.md"

        # Karpathy-compatible format: ## [date] operation | title
        date_str = datetime.now(UTC).strftime("%Y-%m-%d")
        heading = f"## [{date_str}] {operation}"
        if source_name:
            heading += f" | {source_name}"
        entry = f"\n{heading}\n"
        if pages_touched:
            entry += f"pages: {', '.join(pages_touched)}\n"

        # Append to log
        if log_file.exists():
            log_content = log_file.read_text()
            log_file.write_text(log_content + entry)
        else:
            log_file.write_text("# Wiki Log\n" + entry)

        log_entry_id = f"log_{int(datetime.now(UTC).timestamp() * 1000)}"
        return log_entry_id
    except Exception as e:
        _LOG.error(f"Error appending to wiki log: {e}")
        return f"log_{int(datetime.now(UTC).timestamp())}"
