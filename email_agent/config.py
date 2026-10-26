"""Runtime configuration, read from environment variables (GitHub Actions secrets)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field

DIGEST_SUBJECT_PREFIX = "[Daily Digest]"


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


@dataclass
class Config:
    # Claude
    anthropic_api_key: str = field(default_factory=lambda: _env("ANTHROPIC_API_KEY"))
    model: str = field(default_factory=lambda: _env("DIGEST_MODEL", "claude-sonnet-5-5"))
    effort: str = field(default_factory=lambda: _env("DIGEST_EFFORT", "low"))
    # Hard cap per run; 0.065 * 31 days ≈ $2/month even in the worst case.
    daily_budget_usd: float = field(default_factory=lambda: float(_env("DIGEST_DAILY_BUDGET_USD", "0.065")))
    # Bulk mail from these sender substrings still goes to Claude (school notices often look like newsletters).
    important_senders: list[str] = field(default_factory=lambda: [
        s.strip().lower() for s in _env("DIGEST_IMPORTANT_SENDERS", "nus.edu.sg,u.nus.edu,canvas,instructure").split(",")
        if s.strip()])

    # Gmail (IMAP read + SMTP send share one App Password)
    gmail_user: str = field(default_factory=lambda: _env("GMAIL_USER"))
    gmail_app_password: str = field(default_factory=lambda: _env("GMAIL_APP_PASSWORD").replace(" ", ""))

    # NUS (Microsoft 365 via Graph)
    nus_client_id: str = field(default_factory=lambda: _env("NUS_CLIENT_ID"))
    nus_refresh_token: str = field(default_factory=lambda: _env("NUS_REFRESH_TOKEN"))
    nus_tenant: str = field(default_factory=lambda: _env("NUS_TENANT", "organizations"))

    # Digest
    digest_to: str = field(default_factory=lambda: _env("DIGEST_TO"))
    hours: int = field(default_factory=lambda: int(_env("DIGEST_HOURS", "24")))
    timezone: str = field(default_factory=lambda: _env("DIGEST_TZ", "Asia/Singapore"))
    max_body_chars: int = field(default_factory=lambda: int(_env("DIGEST_MAX_BODY_CHARS", "1500")))

    @property
    def recipient(self) -> str:
        return self.digest_to or self.gmail_user
