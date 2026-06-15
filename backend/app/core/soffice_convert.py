"""LibreOffice-based office-to-PDF conversion.

Single home for ``soffice`` subprocess handling so every caller gets the same
hardening: a per-call user-profile directory (concurrent invocations sharing
the default profile deadlock on its lock file), a timeout, and fail-open
``None`` on any error.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)


def soffice_path() -> str | None:
    """Return the ``soffice`` binary path, or ``None`` when LibreOffice is absent."""
    return shutil.which("soffice")


def convert_office_to_pdf(
    source_path: Path,
    out_dir: Path,
    *,
    timeout_sec: float | None = None,
) -> Path | None:
    """Convert an office document (pptx/docx/xlsx) to PDF via LibreOffice.

    Returns the produced PDF path, or ``None`` on any failure (missing binary,
    timeout, non-zero exit). Never raises.
    """
    binary = soffice_path()
    if not binary:
        return None
    if timeout_sec is None:
        from app.core.config import settings

        timeout_sec = settings.soffice_convert_timeout_sec
    profile_dir = tempfile.mkdtemp(prefix="soffice-profile-")
    try:
        subprocess.run(
            [
                binary,
                "--headless",
                "--norestore",
                f"-env:UserInstallation=file://{profile_dir}",
                "--convert-to",
                "pdf",
                "--outdir",
                str(out_dir),
                str(source_path),
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=timeout_sec,
        )
    except subprocess.TimeoutExpired:
        logger.warning("soffice_convert: timed out after %.0fs converting %s", timeout_sec, source_path)
        return None
    except Exception as exc:
        logger.warning("soffice_convert: conversion failed for %s: %s", source_path, exc)
        return None
    finally:
        shutil.rmtree(profile_dir, ignore_errors=True)
    candidate = out_dir / f"{source_path.stem}.pdf"
    return candidate if candidate.exists() else None
