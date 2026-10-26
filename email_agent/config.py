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
    model: str = field(default_factory=lambda: _env("DIGEST_MODEL", "claude-opus-5-5"))
    effort: str = field(default_factory=lambda: _env("DIGEST_EFFORT", "medium"))

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
    max_body_chars: int = field(default_factory=lambda: int(_env("DIGEST_MAX_BODY_CHARS", "4000")))
    batch_size: int = field(default_factory=lambda: int(_env("DIGEST_BATCH_SIZE", "60")))

    @property
    def recipient(self) -> str:
        return self.digest_to or self.gmail_user
