"""Phase 1 security checks: wiki auth, SSRF helper, uploads, zip safety, JWT config."""

import io
import zipfile

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core.office.zip_safety import UnsafeZipError, validate_zip_for_read
from app.main import app
from app.services.http_fetch import SafeFetchError, safe_get


def _auth_header(client: TestClient) -> dict[str, str]:
    r = client.post("/api/auth/login", json={"email": "owner@admin.com", "password": "secret123"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_wiki_health_requires_auth() -> None:
    client = TestClient(app)
    r = client.get("/api/wiki/health")
    assert r.status_code == 401


def test_wiki_health_with_auth() -> None:
    client = TestClient(app)
    h = _auth_header(client)
    r = client.get("/api/wiki/health", headers=h)
    assert r.status_code == 200


def test_wiki_pages_requires_auth() -> None:
    client = TestClient(app)
    r = client.get("/api/wiki/project/pages", params={"project_id": "p_x"})
    assert r.status_code == 401


def test_safe_get_blocks_metadata_ip() -> None:
    with pytest.raises(SafeFetchError):
        safe_get("https://169.254.169.254/latest/meta-data/")


def test_safe_get_rejects_http_scheme() -> None:
    with pytest.raises(SafeFetchError):
        safe_get("http://example.com/")


def test_settings_reject_weak_jwt() -> None:
    from app.core.config import Settings

    with pytest.raises(ValidationError):
        Settings.model_validate(
            {
                "jwt_secret": "change-me",
                "database_url": "sqlite:///:memory:",
            }
        )


def test_upload_rejects_path_traversal_filename() -> None:
    client = TestClient(app)
    h = _auth_header(client)
    pr = client.post("/api/projects", json={"name": "UploadSec"}, headers=h)
    assert pr.status_code == 200
    pid = pr.json()["id"]
    r = client.post(
        "/api/documents/upload",
        headers=h,
        data={"project_id": pid},
        files={"file": ("../../etc/passwd", io.BytesIO(b"x"), "application/octet-stream")},
    )
    assert r.status_code == 400


def test_upload_rejects_bad_project_id() -> None:
    client = TestClient(app)
    h = _auth_header(client)
    r = client.post(
        "/api/documents/upload",
        headers=h,
        data={"project_id": "../bad"},
        files={"file": ("note.txt", io.BytesIO(b"hello"), "text/plain")},
    )
    assert r.status_code == 400


def test_zip_slip_rejected() -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("../evil.txt", "pwnd")
    buf.seek(0)
    with zipfile.ZipFile(buf, "r") as zf:
        with pytest.raises(UnsafeZipError):
            validate_zip_for_read(zf, max_uncompressed_bytes=1024)


def test_wiki_pdf_over_page_limit_rejected() -> None:
    """Wiki ingest text extraction must reject PDFs above the same 50-page cap as document upload."""
    from pypdf import PdfWriter

    from app.services.wiki_ingest import _extract_text_from_file

    buf = io.BytesIO()
    writer = PdfWriter()
    for _ in range(55):
        writer.add_blank_page(width=72, height=72)
    writer.write(buf)
    out = _extract_text_from_file("large.pdf", buf.getvalue())
    assert "50" in out and "reject" in out.lower()
