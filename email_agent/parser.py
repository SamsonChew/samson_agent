"""MIME / HTML -> clean plain text."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from email import message_from_bytes, policy
from email.message import EmailMessage
from email.utils import parsedate_to_datetime

from bs4 import BeautifulSoup

# Lines that start the quoted history of a reply; everything after is dropped.
_QUOTE_MARKERS = [
    re.compile(r"^On .{5,200}wrote:\s*$", re.IGNORECASE),
    re.compile(r"^-{2,}\s*Original Message\s*-{2,}", re.IGNORECASE),
    re.compile(r"^_{10,}\s*$"),  # Outlook separator line before the quoted "From:/Sent:" block
    re.compile(r"^在.{2,100}写道[:：]\s*$"),
]


def html_to_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "head"]):
        tag.decompose()
    for br in soup.find_all("br"):
        br.replace_with("\n")
    text = soup.get_text("\n")
    return normalize_whitespace(text)


def normalize_whitespace(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\xa0", " ")
    lines = [ln.strip() for ln in text.split("\n")]
    text = "\n".join(lines)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def strip_quoted(text: str) -> str:
    """Remove reply history (`> ...` lines and everything after a reply header)."""
    out: list[str] = []
    for i, line in enumerate(text.split("\n")):
        # Only treat a header-like line as a cut point once there is real content above it.
        if i > 0 and out and any(p.match(line) for p in _QUOTE_MARKERS):
            break
        if line.startswith(">"):
            continue
        out.append(line)
    return "\n".join(out).strip()


def truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "\n…[truncated]"


def clean_body(text: str, max_chars: int) -> str:
    return truncate(strip_quoted(normalize_whitespace(text)), max_chars)


def _best_body(msg: EmailMessage) -> str:
    part = msg.get_body(preferencelist=("plain", "html"))
    if part is None:
        return ""
    try:
        content = part.get_content()
    except (LookupError, UnicodeDecodeError):
        payload = part.get_payload(decode=True) or b""
        content = payload.decode("utf-8", errors="replace")
    if part.get_content_type() == "text/html":
        return html_to_text(content)
    return content


def parse_date(value: str | None) -> datetime:
    if value:
        try:
            dt = parsedate_to_datetime(value)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            pass
    return datetime.now(timezone.utc)


def parse_mime(raw: bytes, max_chars: int = 4000) -> dict:
    """Parse raw RFC822 bytes into the fields RawEmail needs."""
    msg = message_from_bytes(raw, policy=policy.default)
    return {
        "message_id": str(msg.get("Message-ID", "")),
        "subject": str(msg.get("Subject", "(no subject)")),
        "sender": str(msg.get("From", "")),
        "received": parse_date(msg.get("Date")),
        "body": clean_body(_best_body(msg), max_chars),
    }
