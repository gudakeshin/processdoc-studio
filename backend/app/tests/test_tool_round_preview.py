"""Tests for tool result previews emitted in the agent_tool_round trace."""

from __future__ import annotations

import json

from app.services.claude_tools import _trace_preview_for_tool


def test_web_capture_preview_happy_path() -> None:
    payload = json.dumps(
        {
            "url": "https://example.com/article",
            "ok": True,
            "title": "Example — article",
            "text": "Paragraph one.\n\nParagraph two explains the rest " + "x" * 400,
            "truncated": True,
            "content_type": "text/html",
        }
    )
    preview = _trace_preview_for_tool("web_capture", payload)
    assert preview is not None
    assert preview["kind"] == "web_capture"
    assert preview["url"] == "https://example.com/article"
    assert preview["title"] == "Example — article"
    assert preview["truncated"] is True
    assert preview["ok"] is True
    assert preview["snippet"].startswith("Paragraph one.")
    assert len(preview["snippet"]) <= 321


def test_web_capture_preview_error() -> None:
    payload = json.dumps(
        {
            "url": "https://example.com/404",
            "ok": False,
            "error": "HTTP 404 fetching target",
            "title": "",
            "text": "",
        }
    )
    preview = _trace_preview_for_tool("web_capture", payload)
    assert preview is not None
    assert preview["ok"] is False
    assert preview["error"] == "HTTP 404 fetching target"
    assert preview["snippet"].startswith("HTTP 404")


def test_preview_none_for_unknown_tools() -> None:
    assert _trace_preview_for_tool("bash", "{}") is None
    assert _trace_preview_for_tool("web_capture", "not-json") is None
    assert _trace_preview_for_tool("web_capture", "") is None


def test_preview_fail_open_on_non_dict_payload() -> None:
    assert _trace_preview_for_tool("web_capture", json.dumps([1, 2, 3])) is None
