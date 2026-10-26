"""Entry point: fetch all mailboxes -> summarize with Claude -> send digest.

    python -m email_agent.main                 # real run (GitHub Actions)
    python -m email_agent.main --dry-run       # fetch + summarize, write HTML locally, don't send
    python -m email_agent.main --dry-run --fixtures email_agent/tests/fixtures --no-llm
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from .config import DIGEST_SUBJECT_PREFIX, Config
from .parser import parse_mime
from .render import render_digest
from .smtp_sender import send_html
from .sources import RawEmail, Source, dedupe
from .sources.graph_source import GraphSource
from .sources.imap_source import IMAPSource
from .summarizer import Digest, Summarizer, fallback_digest

log = logging.getLogger("email_agent")


def build_sources(cfg: Config) -> tuple[list[Source], list[str]]:
    sources: list[Source] = []
    notes: list[str] = []
    if cfg.gmail_user and cfg.gmail_app_password:
        sources.append(IMAPSource("Gmail", "imap.gmail.com", cfg.gmail_user, cfg.gmail_app_password,
                                  max_body_chars=cfg.max_body_chars))
    else:
        notes.append("Gmail 未配置 (GMAIL_USER / GMAIL_APP_PASSWORD)")
    if cfg.nus_client_id and cfg.nus_refresh_token:
        sources.append(GraphSource("NUS", cfg.nus_client_id, cfg.nus_refresh_token, cfg.nus_tenant,
                                   max_body_chars=cfg.max_body_chars))
    else:
        notes.append("NUS 未配置 (NUS_CLIENT_ID / NUS_REFRESH_TOKEN)")
    return sources, notes


def load_fixtures(root: Path, max_chars: int) -> list[RawEmail]:
    """Each subfolder name is the account, each .eml file one email."""
    names = {"gmail": "Gmail", "nus": "NUS"}
    return [RawEmail(account=names.get(p.parent.name, p.parent.name), **parse_mime(p.read_bytes(), max_chars))
            for p in sorted(root.glob("*/*.eml"))]


def collect(sources: list[Source], since: datetime) -> tuple[list[RawEmail], list[str]]:
    emails: list[RawEmail] = []
    errors: list[str] = []
    for src in sources:
        try:
            got = src.fetch(since)
            log.info("%s: %d emails", src.name, len(got))
            emails.extend(got)
        except Exception as exc:  # one broken mailbox must not kill the digest
            log.exception("Fetching %s failed", src.name)
            errors.append(f"{src.name} 抓取失败: {exc}")
    return emails, errors


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="write HTML to --out instead of sending")
    ap.add_argument("--hours", type=int, help="look-back window (default DIGEST_HOURS or 24)")
    ap.add_argument("--fixtures", type=Path, help="read .eml files from this folder instead of mailboxes")
    ap.add_argument("--no-llm", action="store_true", help="skip Claude, list subjects only")
    ap.add_argument("--out", type=Path, default=Path("digest.html"))
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    cfg = Config()
    if args.hours:
        cfg.hours = args.hours
    now = datetime.now(ZoneInfo(cfg.timezone))
    since = now.astimezone(timezone.utc) - timedelta(hours=cfg.hours)

    if args.fixtures:
        emails, errors = load_fixtures(args.fixtures, cfg.max_body_chars), []
    else:
        sources, errors = build_sources(cfg)
        fetched, fetch_errors = collect(sources, since)
        emails, errors = fetched, errors + fetch_errors

    emails = [e for e in dedupe(emails) if not e.subject.startswith(DIGEST_SUBJECT_PREFIX)]
    log.info("%d unique emails to summarize", len(emails))

    digest: Digest
    if args.no_llm or not cfg.anthropic_api_key:
        if not args.no_llm:
            errors.append("未设置 ANTHROPIC_API_KEY，仅列出标题")
        digest = fallback_digest(emails)
    else:
        try:
            digest = Summarizer(cfg.model, cfg.effort, cfg.batch_size, cfg.anthropic_api_key).summarize(emails)
        except Exception as exc:
            log.exception("Claude summarization failed")
            errors.append(f"AI 摘要失败，仅列出标题: {exc}")
            digest = fallback_digest(emails)

    html = render_digest(digest, emails, errors, now)
    n_actions = sum(it.action_required for it in digest.items)
    subject = f"{DIGEST_SUBJECT_PREFIX} {now:%m/%d} · {len(emails)} 封" + (f" · {n_actions} 件待办" if n_actions else "")

    if args.dry_run:
        args.out.write_text(html, encoding="utf-8")
        log.info("Dry run: wrote %s (%s)", args.out, subject)
        return 0

    if not (cfg.gmail_user and cfg.gmail_app_password and cfg.recipient):
        log.error("Cannot send: GMAIL_USER / GMAIL_APP_PASSWORD / DIGEST_TO not set")
        return 1
    send_html(cfg.gmail_user, cfg.gmail_app_password, cfg.recipient, subject, html)
    log.info("Sent digest to %s: %s", cfg.recipient, subject)
    return 0


if __name__ == "__main__":
    sys.exit(main())
