"""Send the sign-in code by email (SMTP). Without SMTP_HOST the code is only written to the server log."""

import logging
import smtplib
import ssl
from email.message import EmailMessage

from .config import settings

log = logging.getLogger("greenmedia.mail")

# Swappable in tests.
smtp_factory = None


class MailError(Exception):
    pass


def enabled() -> bool:
    return bool(settings.smtp_host)


def describe() -> str:
    """One line for the startup log: how sign-in emails are sent."""
    if enabled():
        return f"Email: SMTP {settings.smtp_host}:{settings.smtp_port} from {settings.smtp_from or settings.smtp_user or '(no SMTP_FROM)'}"
    return "Email: none — email sign-in codes are only written to this log (set SMTP_HOST to send real email)"


def masked(email: str) -> str:
    """an••••@gmail.com"""
    name, _, domain = email.partition("@")
    return f"{name[:2]}••••@{domain}"


def send_otp(email: str, code: str) -> str:
    """Raises MailError when the mail server refuses."""
    minutes = settings.otp_ttl_seconds // 60
    if not enabled():
        log.warning("Email OTP for %s: %s (no SMTP_HOST — set it to send real email)", email, code)
        return "console: written to the server log only"
    msg = EmailMessage()
    msg["Subject"] = f"{code} is your Green Media sign-in code"
    msg["From"] = settings.smtp_from or settings.smtp_user
    msg["To"] = email
    msg.set_content(f"Your Green Media sign-in code is {code}.\n\nIt expires in {minutes} minutes. "
                    "If you didn't ask for it, you can ignore this email; nobody can sign in without the code.\n")
    try:
        if smtp_factory:
            server = smtp_factory()
        elif settings.smtp_port == 465:
            server = smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=20, context=ssl.create_default_context())
        else:
            server = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20)
        with server:
            if not smtp_factory and settings.smtp_port != 465:
                server.starttls(context=ssl.create_default_context())
            if settings.smtp_user:
                server.login(settings.smtp_user, settings.smtp_password)
            server.send_message(msg)
    except (smtplib.SMTPException, OSError) as e:
        raise MailError(f"{e.__class__.__name__}: {e}"[:200]) from e
    return "sent"
