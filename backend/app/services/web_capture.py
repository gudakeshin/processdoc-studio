"""SSRF-safe web capture tool.

Wraps :func:`app.services.http_fetch.safe_get` to fetch remote HTML/text
resources and return a readable, size-capped payload suitable for agent
consumption. All of the SSRF protections in ``safe_get`` apply (HTTPS-only,
DNS resolution pre-check, private/loopback IP blocking, redirect re-validation,
bounded read size), so this wrapper focuses on:

- Decoding response bytes as text (charset-aware, with a utf-8 fallback).
- Extracting a reasonable ``title`` and readable plaintext from HTML.
- Capping the returned text to keep prompts within budget.
- Returning a stable, deterministic structure suitable for JSON serialization.

The module is intentionally dependency-light: it only uses the stdlib plus the
existing ``safe_get`` helper. This keeps the tool available in every runtime
environment and avoids introducing new fetch libraries that could bypass the
central SSRF policy.
"""

from __future__ import annotations

import html
import logging
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any

from app.services.http_fetch import SafeFetchError, safe_get

logger = logging.getLogger(__name__)


_DEFAULT_MAX_CHARS = 8_000
_HARD_MAX_CHARS = 32_000
_SKIP_TAGS = frozenset({"script", "style", "noscript", "template", "svg", "iframe"})


@dataclass
class WebCaptureResult:
    """Structured capture payload returned by :func:`web_capture`."""

    url: str
    ok: bool
    title: str = ""
    text: str = ""
    text_chars: int = 0
    truncated: bool = False
    content_type: str = ""
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "ok": self.ok,
            "title": self.title,
            "text": self.text,
            "text_chars": self.text_chars,
            "truncated": self.truncated,
            "content_type": self.content_type,
            "error": self.error,
        }


class _ReadableTextExtractor(HTMLParser):
    """Minimal HTML-to-text extractor that keeps title and body text only."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self._in_title = False
        self._title_parts: list[str] = []
        self._text_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:  # noqa: ARG002
        lowered = tag.lower()
        if lowered in _SKIP_TAGS:
            self._skip_depth += 1
        elif lowered == "title":
            self._in_title = True
        elif lowered in {"p", "div", "section", "article", "li", "br", "tr", "h1", "h2", "h3", "h4", "h5", "h6"}:
            self._text_parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        lowered = tag.lower()
        if lowered in _SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1
        elif lowered == "title":
            self._in_title = False
        elif lowered in {"p", "div", "section", "article", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6"}:
            self._text_parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth > 0:
            return
        if self._in_title:
            self._title_parts.append(data)
        else:
            self._text_parts.append(data)

    @property
    def title(self) -> str:
        return re.sub(r"\s+", " ", "".join(self._title_parts)).strip()

    @property
    def text(self) -> str:
        raw = "".join(self._text_parts)
        collapsed = re.sub(r"[ \t]+", " ", raw)
        collapsed = re.sub(r"\n{3,}", "\n\n", collapsed)
        lines = [line.strip() for line in collapsed.splitlines()]
        return "\n".join(line for line in lines if line).strip()


def _decode_body(body: bytes, content_type: str) -> str:
    charset = ""
    if content_type:
        match = re.search(r"charset=([A-Za-z0-9_\-:]+)", content_type)
        if match:
            charset = match.group(1).strip().lower()
    for candidate in [charset, "utf-8", "latin-1"]:
        if not candidate:
            continue
        try:
            return body.decode(candidate)
        except (UnicodeDecodeError, LookupError):
            continue
    return body.decode("utf-8", errors="replace")


def _looks_like_html(content_type: str, body_text: str) -> bool:
    if "html" in (content_type or "").lower():
        return True
    snippet = body_text[:2048].lower()
    return "<html" in snippet or "<!doctype html" in snippet or "<body" in snippet


def _extract_plaintext(body_text: str, content_type: str) -> tuple[str, str]:
    if _looks_like_html(content_type, body_text):
        parser = _ReadableTextExtractor()
        try:
            parser.feed(body_text)
            parser.close()
        except Exception as exc:  # pragma: no cover - HTMLParser rarely raises
            logger.warning("web_capture: HTML parse failed (%s)", exc)
            return "", html.unescape(body_text).strip()
        return parser.title, parser.text
    return "", body_text.strip()


def web_capture(
    url: str | None = None,
    *,
    max_chars: int | None = None,
    max_bytes: int | None = None,
    timeout: float | None = None,
) -> dict[str, Any]:
    """Fetch ``url`` via SSRF-safe GET and return a structured text capture.

    Parameters
    ----------
    url: the HTTPS URL to fetch. Only HTTPS is accepted (enforced by ``safe_get``).
    max_chars: upper bound on the returned text, defaults to 8_000 (hard cap 32_000).
    max_bytes: overrides the byte cap on response body (defaults to
        ``settings.http_fetch_max_bytes``).
    timeout: overrides the request timeout in seconds.
    """

    target = (url or "").strip()
    result = WebCaptureResult(url=target, ok=False)
    if not target:
        result.error = "url is required"
        return result.to_dict()

    cap = max_chars if isinstance(max_chars, int) else _DEFAULT_MAX_CHARS
    cap = max(500, min(int(cap), _HARD_MAX_CHARS))

    content_type = ""
    try:
        body = safe_get(target, max_bytes=max_bytes, timeout=timeout)
    except SafeFetchError as exc:
        result.error = str(exc)
        return result.to_dict()
    except Exception as exc:  # defensive — never let the agent loop crash on fetch errors
        logger.warning("web_capture: unexpected fetch error for %s: %s", target, exc)
        result.error = f"fetch error: {exc}"
        return result.to_dict()

    body_text = _decode_body(body, content_type)
    title, text = _extract_plaintext(body_text, content_type)
    truncated = len(text) > cap
    text_out = text[:cap]
    result.ok = True
    result.title = title[:500]
    result.text = text_out
    result.text_chars = len(text_out)
    result.truncated = truncated
    result.content_type = content_type
    return result.to_dict()
