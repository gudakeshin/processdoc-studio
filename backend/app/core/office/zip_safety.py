"""Zip-slip and zip-bomb guards for in-memory or on-disk zip handling."""

from __future__ import annotations

import zipfile
from pathlib import Path, PurePosixPath


class UnsafeZipError(ValueError):
    """Raised when a zip archive fails structural or size safety checks."""


def assert_zip_member_paths_safe(zf: zipfile.ZipFile) -> None:
    """Reject absolute paths, parent segments, and zip-slip-style member names."""
    for info in zf.infolist():
        name = info.filename
        if not name:
            raise UnsafeZipError("Empty zip member name")
        if name.startswith(("/", "\\")):
            raise UnsafeZipError(f"Absolute zip member path: {name!r}")
        parts = PurePosixPath(name).parts
        if ".." in parts:
            raise UnsafeZipError(f"Unsafe zip member path: {name!r}")
        # Windows-style drive letters in archives
        if len(parts) >= 1 and parts[0].endswith(":"):
            raise UnsafeZipError(f"Unsafe zip member path: {name!r}")


def assert_zip_uncompressed_size(zf: zipfile.ZipFile, *, max_uncompressed_bytes: int) -> None:
    """Reject archives whose declared uncompressed total exceeds the cap."""
    total = sum(info.file_size for info in zf.infolist())
    if total > max_uncompressed_bytes:
        raise UnsafeZipError(
            f"Zip uncompressed size {total} exceeds limit {max_uncompressed_bytes}"
        )


def validate_zip_for_read(zf: zipfile.ZipFile, *, max_uncompressed_bytes: int) -> None:
    """Run zip-slip and zip-bomb checks before reading members."""
    assert_zip_member_paths_safe(zf)
    assert_zip_uncompressed_size(zf, max_uncompressed_bytes=max_uncompressed_bytes)


def safe_extract_all(zf: zipfile.ZipFile, target_dir: Path, *, max_uncompressed_bytes: int) -> None:
    """Extract only after path + size checks; assert each member stays under target_dir.

    Declared uncompressed sizes in zip metadata can be spoofed (zip-bomb variant).
    This function extracts member-by-member and tracks actual bytes written so the
    cap is enforced on real decompressed output, not just declared metadata.
    """
    validate_zip_for_read(zf, max_uncompressed_bytes=max_uncompressed_bytes)
    root = target_dir.resolve()
    root.mkdir(parents=True, exist_ok=True)
    for info in zf.infolist():
        dest = (root / info.filename).resolve()
        if root not in dest.parents and dest != root:
            raise UnsafeZipError(f"Zip-slip: member {info.filename!r} resolves outside target")

    # Extract member-by-member and count actual bytes to catch spoofed declared sizes.
    actual_bytes = 0
    for info in zf.infolist():
        dest = (root / info.filename).resolve()
        if info.filename.endswith("/"):
            dest.mkdir(parents=True, exist_ok=True)
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        with zf.open(info) as src, dest.open("wb") as out:
            while True:
                chunk = src.read(65536)
                if not chunk:
                    break
                actual_bytes += len(chunk)
                if actual_bytes > max_uncompressed_bytes:
                    raise UnsafeZipError(
                        f"Actual extracted size exceeds limit {max_uncompressed_bytes} "
                        f"(declared size was within limit — possible zip-bomb)"
                    )
                out.write(chunk)
