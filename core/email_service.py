"""
core/email_service.py
─────────────────────
Pluggable email service for FinanceFlow AI.

Supported providers (set EMAIL_PROVIDER in .env):
    dry_run   — logs to JSONL file, never sends (default / safe for testing)
    smtp      — sends via any SMTP server (Gmail, Outlook, custom)
    sendgrid  — sends via SendGrid HTTP API
    mailgun   — sends via Mailgun HTTP API

All configuration is read from environment variables.
No credentials are ever hardcoded.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv

load_dotenv()

# ─── Types ───────────────────────────────────────────────────────────────────

EmailProvider = Literal["dry_run", "sendgrid"]

DRY_RUN_LOG_PATH = Path(os.getenv("DRY_RUN_LOG_PATH", "logs/email_dry_run.jsonl"))


# ─── Result dataclass ────────────────────────────────────────────────────────

class SendResult:
    def __init__(
        self,
        success: bool,
        provider: str,
        message: str,
        dry_run: bool = False,
    ):
        self.success  = success
        self.provider = provider
        self.message  = message
        self.dry_run  = dry_run

    def __repr__(self) -> str:
        status = "DRY-RUN" if self.dry_run else ("OK" if self.success else "FAILED")
        return f"<SendResult [{status}] via {self.provider}: {self.message}>"


# ═════════════════════════════════════════════════════════════════════════════
#  PROVIDER IMPLEMENTATIONS
# ═════════════════════════════════════════════════════════════════════════════

def _send_dry_run(
    to: str,
    subject: str,
    body: str,
    invoice_no: str,
    tone: str,
) -> SendResult:
    """
    Dry-run mode: write a structured log entry to a JSONL file.
    No network calls are made. Safe for development and CI.
    """
    DRY_RUN_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

    log_entry = {
        "timestamp":  datetime.now(timezone.utc).isoformat(),
        "mode":       "dry_run",
        "invoice_no": invoice_no,
        "to":         to,
        "subject":    subject,
        "tone":       tone,
        "body":       body,
    }

    with DRY_RUN_LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")

    print(f"[DRY-RUN] Email logged → {DRY_RUN_LOG_PATH}")
    return SendResult(
        success=True,
        provider="dry_run",
        message=f"Logged to {DRY_RUN_LOG_PATH}",
        dry_run=True,
    )

def _send_sendgrid(
    to: str,
    subject: str,
    body: str,
) -> SendResult:
    """
    Send via SendGrid HTTP API (no SDK dependency — pure requests).

    Required env vars:
        SENDGRID_API_KEY
        SENDGRID_FROM     verified sender address
    """
    try:
        import requests
    except ImportError as e:
        raise RuntimeError("Install 'requests': pip install requests") from e

    api_key   = os.environ["SENDGRID_API_KEY"]
    from_addr = os.environ["SENDGRID_FROM"]

    payload = {
        "personalizations": [{"to": [{"email": to}]}],
        "from":             {"email": from_addr},
        "subject":          subject,
        "content":          [{"type": "text/plain", "value": body}],
    }

    resp = requests.post(
        "https://api.sendgrid.com/v3/mail/send",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type":  "application/json",
        },
        json=payload,
        timeout=15,
    )

    if resp.status_code in (200, 202):
        return SendResult(success=True, provider="sendgrid", message=f"Accepted for {to}")

    return SendResult(
        success=False,
        provider="sendgrid",
        message=f"HTTP {resp.status_code}: {resp.text[:200]}",
    )

# ═════════════════════════════════════════════════════════════════════════════
#  PUBLIC API
# ═════════════════════════════════════════════════════════════════════════════

def send_email(
    to: str,
    subject: str,
    body: str,
    invoice_no: str = "",
    tone: str = "",
) -> SendResult:
    """
    Dispatch an email using the provider configured in EMAIL_PROVIDER env var.

    EMAIL_PROVIDER options: dry_run (default) | smtp | sendgrid | mailgun

    Examples
    --------
    # .env
    EMAIL_PROVIDER=dry_run           # always safe during development
    EMAIL_PROVIDER=sendgrid          # use with SENDGRID_API_KEY, SENDGRID_FROM
    """
    provider: EmailProvider = os.getenv("EMAIL_PROVIDER", "dry_run").lower().strip()

    if provider == "dry_run":
        return _send_dry_run(to, subject, body, invoice_no, tone)

    if provider == "sendgrid":
        return _send_sendgrid(to, subject, body)

    raise ValueError(
        f"Unknown EMAIL_PROVIDER='{provider}'. "
        "Valid options: dry_run | sendgrid"
    )