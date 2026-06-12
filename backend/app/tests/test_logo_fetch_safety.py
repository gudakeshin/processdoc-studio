"""Tests for the SSRF-safe branding logo fetch shared by the PPTX renderers."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.deliverable_utils import fetch_logo_source
from app.services import http_fetch as http_fetch_module
from app.services.http_fetch import SafeFetchError


def test_blocked_url_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    def _blocked(url: str, **kwargs):  # noqa: ARG001
        raise SafeFetchError("Blocked IP for SSRF protection: 169.254.169.254")

    monkeypatch.setattr(http_fetch_module, "safe_get", _blocked)
    assert fetch_logo_source("https://attacker.example/logo.png") is None


def test_remote_logo_saved_to_temp_with_suffix(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = b"\x89PNG fake-logo-bytes"

    def _ok(url: str, **kwargs):  # noqa: ARG001
        return payload

    monkeypatch.setattr(http_fetch_module, "safe_get", _ok)
    source = fetch_logo_source("https://cdn.example.com/brand/logo.png?v=2")
    assert source is not None
    p = Path(source)
    try:
        assert p.suffix == ".png"
        assert p.read_bytes() == payload
    finally:
        p.unlink(missing_ok=True)


def test_local_path_passthrough(tmp_path: Path) -> None:
    logo = tmp_path / "logo.svg"
    logo.write_bytes(b"<svg/>")
    assert fetch_logo_source(str(logo)) == str(logo)


def test_missing_local_path_returns_none(tmp_path: Path) -> None:
    assert fetch_logo_source(str(tmp_path / "absent.png")) is None


def test_empty_url_returns_none() -> None:
    assert fetch_logo_source("") is None
    assert fetch_logo_source("   ") is None
