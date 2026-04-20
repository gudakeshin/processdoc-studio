"""Tests for the SSRF-safe web_capture tool (PPT-302)."""

from __future__ import annotations

import pytest

from app.services import web_capture as web_capture_module
from app.services.http_fetch import SafeFetchError
from app.services.tool_registry import _TOOL_METADATA, TOOL_REGISTRY


def test_web_capture_tool_registered_with_schema() -> None:
    assert "web_capture" in TOOL_REGISTRY
    schema = _TOOL_METADATA.get("web_capture")
    assert schema is not None
    assert "url" in schema["input_schema"]["properties"]
    assert schema["input_schema"]["required"] == ["url"]


def test_web_capture_rejects_missing_url() -> None:
    result = web_capture_module.web_capture("")
    assert result["ok"] is False
    assert "url" in (result.get("error") or "").lower()


def test_web_capture_propagates_ssrf_block(monkeypatch: pytest.MonkeyPatch) -> None:
    def _blocked(url: str, **kwargs):  # noqa: ARG001
        raise SafeFetchError("Blocked IP for SSRF protection: 127.0.0.1")

    monkeypatch.setattr(web_capture_module, "safe_get", _blocked)
    result = web_capture_module.web_capture("https://attacker.example/internal")
    assert result["ok"] is False
    assert "SSRF" in (result.get("error") or "") or "Blocked" in (result.get("error") or "")


def test_web_capture_parses_html_title_and_text(monkeypatch: pytest.MonkeyPatch) -> None:
    html_body = (
        b"<!doctype html><html><head><title>Finance Transformation</title>"
        b"<script>var x=1;</script><style>body{color:red}</style>"
        b"</head><body><h1>Finance Transformation</h1>"
        b"<p>We analyzed the close cycle.</p>"
        b"<p>Automation reduces rework.</p>"
        b"<noscript>fallback</noscript></body></html>"
    )

    def _ok(url: str, **kwargs):  # noqa: ARG001
        return html_body

    monkeypatch.setattr(web_capture_module, "safe_get", _ok)
    result = web_capture_module.web_capture("https://example.com/report", max_chars=2000)
    assert result["ok"] is True
    assert result["title"] == "Finance Transformation"
    assert "We analyzed the close cycle." in result["text"]
    assert "Automation reduces rework." in result["text"]
    assert "var x=1;" not in result["text"]
    assert "color:red" not in result["text"]
    assert result["truncated"] is False
    assert result["text_chars"] == len(result["text"])


def test_web_capture_respects_max_chars_truncation(monkeypatch: pytest.MonkeyPatch) -> None:
    body = b"<html><body>" + (b"alpha beta gamma " * 400) + b"</body></html>"

    def _ok(url: str, **kwargs):  # noqa: ARG001
        return body

    monkeypatch.setattr(web_capture_module, "safe_get", _ok)
    result = web_capture_module.web_capture("https://example.com/long", max_chars=600)
    assert result["ok"] is True
    assert result["text_chars"] == 600
    assert result["truncated"] is True


def test_web_capture_handles_plain_text(monkeypatch: pytest.MonkeyPatch) -> None:
    def _ok(url: str, **kwargs):  # noqa: ARG001
        return b"Plain text resource without markup\nsecond line"

    monkeypatch.setattr(web_capture_module, "safe_get", _ok)
    result = web_capture_module.web_capture("https://example.com/robots.txt")
    assert result["ok"] is True
    assert result["title"] == ""
    assert "Plain text resource" in result["text"]


def test_web_capture_fail_open_on_unexpected_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _boom(url: str, **kwargs):  # noqa: ARG001
        raise RuntimeError("network stack exploded")

    monkeypatch.setattr(web_capture_module, "safe_get", _boom)
    result = web_capture_module.web_capture("https://example.com/x")
    assert result["ok"] is False
    assert "fetch error" in (result.get("error") or "").lower()


def test_web_capture_tool_handler_normalizes_kwargs(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def _stub(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return {"ok": True, "url": url, "title": "", "text": "", "text_chars": 0, "truncated": False, "content_type": "", "error": None}

    monkeypatch.setattr("app.services.tool_registry._web_capture_impl", _stub)
    from app.services.tool_registry import web_capture as handler

    handler(url="https://example.com/a", max_chars="1500", timeout="3.5", max_bytes="not-an-int")
    assert captured["url"] == "https://example.com/a"
    assert captured.get("max_chars") == 1500
    assert captured.get("timeout") == 3.5
    assert "max_bytes" not in captured  # invalid value dropped silently
