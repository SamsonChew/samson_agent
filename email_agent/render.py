"""Render the digest to HTML."""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .sources import RawEmail
from .summarizer import CATEGORIES, Digest

_env = Environment(
    loader=FileSystemLoader(Path(__file__).parent / "templates"),
    autoescape=select_autoescape(["html", "j2"]),
)


def render_digest(digest: Digest, emails: list[RawEmail], errors: list[str], now: datetime) -> str:
    rows = []
    for it in digest.items:
        e = emails[it.email_id]
        rows.append({"item": it, "email": e})

    actions = sorted((r for r in rows if r["item"].action_required),
                     key=lambda r: (r["item"].priority, r["email"].received))
    by_category = {
        cat: sorted((r for r in rows if r["item"].category == cat and not r["item"].action_required),
                    key=lambda r: (r["item"].priority, -r["email"].received.timestamp()))
        for cat in CATEGORIES
    }
    return _env.get_template("digest.html.j2").render(
        date=now.strftime("%Y-%m-%d %a"),
        tldr=digest.tldr,
        actions=actions,
        by_category={k: v for k, v in by_category.items() if v},
        per_account=Counter(e.account for e in emails),
        total=len(emails),
        promo_count=len(by_category.get("推广", [])),
        errors=errors,
    )
