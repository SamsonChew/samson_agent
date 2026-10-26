"""Common email shape shared by every mailbox source."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, Protocol


@dataclass
class RawEmail:
    account: str  # "Gmail" / "NUS"
    message_id: str
    subject: str
    sender: str
    received: datetime  # timezone-aware
    body: str  # cleaned plain text
    link: str = ""  # deep link back to the original message, if known
    bulk: bool = False  # mailing list / newsletter / marketing (List-Unsubscribe, Precedence: bulk)


class Source(Protocol):
    name: str

    def fetch(self, since: datetime) -> list[RawEmail]: ...


def dedupe(emails: Iterable[RawEmail]) -> list[RawEmail]:
    """Drop duplicates (same Message-ID delivered to both mailboxes), keep newest-first order."""
    seen: set[str] = set()
    out: list[RawEmail] = []
    for e in sorted(emails, key=lambda e: e.received, reverse=True):
        key = e.message_id.strip().lower() or f"{e.account}|{e.sender}|{e.subject}|{e.received.isoformat()}"
        if key in seen:
            continue
        seen.add(key)
        out.append(e)
    return out
