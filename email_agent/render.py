"""Render the digest to HTML."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .sources import RawEmail
from .summarizer import CATEGORIES, Digest

_env = Environment(
    loader=FileSystemLoader(Path(__file__).parent / "templates"),
    autoescape=select_autoescape(["html", "j2"]),
)


def _sender_name(sender: str) -> str:
    name = sender.split("<")[0].strip().strip('"')
    return name or sender.strip("<>")


def render_digest(digest: Digest, emails: list[RawEmail], bulk: list[RawEmail],
                  errors: list[str], now: datetime) -> str:
    """`emails` are the ones digest.items index into; `bulk` is listed by sender without AI."""
    rows = [{"item": it, "email": emails[it.email_id]} for it in digest.items]

    actions = sorted((r for r in rows if r["item"].action_required),
                     key=lambda r: (r["item"].priority, r["email"].received))
    by_category = {
        cat: sorted((r for r in rows if r["item"].category == cat and not r["item"].action_required),
                    key=lambda r: (r["item"].priority, -r["email"].received.timestamp()))
        for cat in CATEGORIES
    }
    bulk_by_sender: dict[str, list[RawEmail]] = defaultdict(list)
    for e in bulk:
        bulk_by_sender[_sender_name(e.sender)].append(e)

    return _env.get_template("digest.html.j2").render(
        date=now.strftime("%Y-%m-%d %a"),
        tldr=digest.tldr,
        actions=actions,
        by_category={k: v for k, v in by_category.items() if v},
        bulk_by_sender=sorted(bulk_by_sender.items(), key=lambda kv: -len(kv[1])),
        per_account=Counter(e.account for e in emails + bulk),
        total=len(emails) + len(bulk),
        bulk_count=len(bulk),
        cost_usd=digest.cost_usd,
        errors=errors,
    )
