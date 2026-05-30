"""Minimal stdlib SMTP email delivery.

Used by the financial report generator to deliver generated files. Email is
optional: when ``smtp_host`` is unset, ``send_email`` returns a structured
``{"sent": False, "reason": "email_not_configured"}`` rather than raising or
silently dropping the request, so callers can surface an honest status to the UI.
"""

from __future__ import annotations

import logging
import mimetypes
import smtplib
from email.message import EmailMessage
from pathlib import Path

from app.core.config import settings

log = logging.getLogger(__name__)


def send_email(
    to: list[str],
    subject: str,
    body: str,
    attachments: list[Path] | None = None,
) -> dict[str, object]:
    """Send an email with optional file attachments.

    Returns a dict: ``{"sent": bool, "reason": str | None, "recipients": list[str]}``.
    Never raises on configuration or transport errors — failures are reported in
    the return value so the caller can keep the primary operation (report
    generation) successful and tell the user email did not go through.
    """
    recipients = [addr.strip() for addr in to if addr and addr.strip()]
    if not recipients:
        return {"sent": False, "reason": "no_recipients", "recipients": []}

    if not settings.smtp_host:
        return {"sent": False, "reason": "email_not_configured", "recipients": recipients}

    msg = EmailMessage()
    msg["From"] = settings.smtp_from or settings.smtp_username or "no-reply@localhost"
    msg["To"] = ", ".join(recipients)
    msg["Subject"] = subject
    msg.set_content(body)

    for path in attachments or []:
        try:
            data = path.read_bytes()
        except OSError:
            log.warning("Skipping unreadable email attachment: %s", path, exc_info=True)
            continue
        ctype, _ = mimetypes.guess_type(path.name)
        maintype, _, subtype = (ctype or "application/octet-stream").partition("/")
        msg.add_attachment(data, maintype=maintype, subtype=subtype or "octet-stream", filename=path.name)

    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as smtp:
            if settings.smtp_use_tls:
                smtp.starttls()
            if settings.smtp_username:
                smtp.login(settings.smtp_username, settings.smtp_password)
            smtp.send_message(msg)
    except (smtplib.SMTPException, OSError) as exc:
        log.warning("Email delivery failed: %s", exc, exc_info=True)
        return {"sent": False, "reason": "send_failed", "recipients": recipients}

    return {"sent": True, "reason": None, "recipients": recipients}
