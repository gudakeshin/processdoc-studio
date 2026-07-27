from app.services import email_service


def test_send_email_not_configured(monkeypatch):
    """With no SMTP host, email is reported as not configured — never silently dropped."""
    monkeypatch.setattr(email_service.settings, "smtp_host", "")
    out = email_service.send_email(["a@b.com"], "Subject", "Body")
    assert out["sent"] is False
    assert out["reason"] == "email_not_configured"
    assert out["recipients"] == ["a@b.com"]


def test_send_email_no_recipients(monkeypatch):
    monkeypatch.setattr(email_service.settings, "smtp_host", "smtp.test")
    out = email_service.send_email(["", "   "], "Subject", "Body")
    assert out["sent"] is False
    assert out["reason"] == "no_recipients"


def test_send_email_attaches_file_and_sends(monkeypatch, tmp_path):
    monkeypatch.setattr(email_service.settings, "smtp_host", "smtp.test")
    monkeypatch.setattr(email_service.settings, "smtp_username", "")
    monkeypatch.setattr(email_service.settings, "smtp_use_tls", False)

    captured: dict = {}

    class FakeSMTP:
        def __init__(self, host, port, timeout=30):
            captured["host"] = host

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def starttls(self):
            captured["tls"] = True

        def login(self, user, password):
            captured["login"] = (user, password)

        def send_message(self, msg):
            captured["msg"] = msg

    monkeypatch.setattr(email_service.smtplib, "SMTP", FakeSMTP)

    report = tmp_path / "Q4_Report.xlsx"
    report.write_bytes(b"binary-xlsx-bytes")

    out = email_service.send_email(["a@b.com", " c@d.com "], "Q4", "Attached.", attachments=[report])

    assert out["sent"] is True
    assert out["reason"] is None
    assert out["recipients"] == ["a@b.com", "c@d.com"]
    assert captured["host"] == "smtp.test"
    assert "tls" not in captured  # smtp_use_tls False → starttls not called

    attachments = list(captured["msg"].iter_attachments())
    assert len(attachments) == 1
    assert attachments[0].get_filename() == "Q4_Report.xlsx"
