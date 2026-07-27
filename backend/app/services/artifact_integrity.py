"""Integrity helpers for run-folder binary deliverables (PPTX, etc.)."""

from __future__ import annotations

import base64
import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from app.core.tz import IST

PPTX_INTEGRITY_FILENAME = "pptx_integrity.json"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    return sha256_bytes(path.read_bytes())


def write_pptx_integrity_manifest(run_dir: Path) -> dict[str, Any] | None:
    """Record digests for output.pptx and pptx_slides.json after render/save."""
    pptx_path = run_dir / "output.pptx"
    if not pptx_path.is_file():
        return None
    pptx_bytes = pptx_path.read_bytes()
    slides_path = run_dir / "pptx_slides.json"
    slides_sha = sha256_file(slides_path) if slides_path.is_file() else None
    manifest: dict[str, Any] = {
        "output_pptx_sha256": sha256_bytes(pptx_bytes),
        "output_pptx_size_bytes": len(pptx_bytes),
        "pptx_slides_sha256": slides_sha,
        "updated_at": datetime.now(IST).isoformat(),
    }
    (run_dir / PPTX_INTEGRITY_FILENAME).write_text(
        json.dumps(manifest, indent=2),
        encoding="utf-8",
    )
    return manifest


def read_pptx_integrity_manifest(run_dir: Path) -> dict[str, Any] | None:
    path = run_dir / PPTX_INTEGRITY_FILENAME
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def verify_pptx_on_disk(run_dir: Path) -> dict[str, Any]:
    """
    Verify output.pptx on disk and compare with the stored integrity manifest.

    Returns a dict with ok, sha256, size_bytes, and optional mismatch details.
    """
    pptx_path = run_dir / "output.pptx"
    if not pptx_path.is_file():
        return {"ok": False, "reason": "missing_output_pptx"}

    pptx_bytes = pptx_path.read_bytes()
    actual_sha = sha256_bytes(pptx_bytes)
    actual_size = len(pptx_bytes)
    manifest = read_pptx_integrity_manifest(run_dir)
    expected_sha = str((manifest or {}).get("output_pptx_sha256") or "").strip()
    expected_size = (manifest or {}).get("output_pptx_size_bytes")

    stale_manifest = bool(
        manifest
        and expected_sha
        and (actual_sha != expected_sha or (isinstance(expected_size, int) and expected_size != actual_size))
    )
    if stale_manifest:
        # Refresh manifest so subsequent downloads stay aligned with disk truth.
        write_pptx_integrity_manifest(run_dir)

    slides_path = run_dir / "pptx_slides.json"
    slides_newer_than_pptx = False
    if slides_path.is_file():
        slides_newer_than_pptx = slides_path.stat().st_mtime > pptx_path.stat().st_mtime + 0.001

    return {
        "ok": True,
        "sha256": actual_sha,
        "size_bytes": actual_size,
        "manifest_stale": stale_manifest,
        "slides_newer_than_pptx": slides_newer_than_pptx,
        "expected_sha256": expected_sha or None,
    }


def pptx_base64_from_file(run_dir: Path) -> tuple[str, dict[str, Any]]:
    """Read output.pptx from disk, verify integrity, return (base64, integrity_meta)."""
    check = verify_pptx_on_disk(run_dir)
    if not check.get("ok"):
        return "", check
    pptx_bytes = (run_dir / "output.pptx").read_bytes()
    encoded = base64.b64encode(pptx_bytes).decode("ascii")
    decoded_ok = base64.b64decode(encoded) == pptx_bytes
    check["base64_matches_file"] = decoded_ok
    return encoded, check


def assert_base64_matches_file(b64: str, path: Path) -> bool:
    if not b64 or not path.is_file():
        return False
    try:
        decoded = base64.b64decode(b64, validate=True)
    except Exception:
        return False
    return decoded == path.read_bytes()
