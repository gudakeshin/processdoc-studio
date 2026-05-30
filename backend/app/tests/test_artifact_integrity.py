"""Tests for PPTX artifact integrity helpers."""

from __future__ import annotations

import base64
from pathlib import Path

from app.services.artifact_integrity import (
    assert_base64_matches_file,
    pptx_base64_from_file,
    verify_pptx_on_disk,
    write_pptx_integrity_manifest,
)


def test_write_and_verify_pptx_integrity(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "r1"
    run_dir.mkdir(parents=True)
    pptx_bytes = b"fake-pptx-bytes-for-integrity"
    (run_dir / "output.pptx").write_bytes(pptx_bytes)
    (run_dir / "pptx_slides.json").write_text('[{"title": "Intro"}]', encoding="utf-8")

    manifest = write_pptx_integrity_manifest(run_dir)
    assert manifest is not None
    assert manifest["output_pptx_size_bytes"] == len(pptx_bytes)

    check = verify_pptx_on_disk(run_dir)
    assert check["ok"] is True
    assert check["manifest_stale"] is False


def test_pptx_base64_matches_on_disk_file(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "r2"
    run_dir.mkdir(parents=True)
    pptx_bytes = b"canonical-output-pptx"
    (run_dir / "output.pptx").write_bytes(pptx_bytes)
    write_pptx_integrity_manifest(run_dir)

    b64, meta = pptx_base64_from_file(run_dir)
    assert meta["ok"] is True
    assert meta["base64_matches_file"] is True
    assert assert_base64_matches_file(b64, run_dir / "output.pptx")
    assert base64.b64decode(b64) == pptx_bytes


def test_stale_manifest_is_refreshed_when_pptx_changes(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "r3"
    run_dir.mkdir(parents=True)
    (run_dir / "output.pptx").write_bytes(b"version-one")
    write_pptx_integrity_manifest(run_dir)

    (run_dir / "output.pptx").write_bytes(b"version-two-updated")
    check = verify_pptx_on_disk(run_dir)
    assert check["ok"] is True
    assert check["manifest_stale"] is True

    refreshed_b64, refreshed_meta = pptx_base64_from_file(run_dir)
    assert refreshed_meta["manifest_stale"] is False
    assert base64.b64decode(refreshed_b64) == b"version-two-updated"
