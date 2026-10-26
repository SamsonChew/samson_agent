"""Generic IMAP source (used for Gmail). Read-only: messages are not marked as read."""

from __future__ import annotations

import imaplib
import re
from datetime import datetime

from ..parser import parse_mime
from .base import RawEmail

_THRID_RE = re.compile(rb"X-GM-THRID (\d+)")


class IMAPSource:
    def __init__(self, name: str, host: str, user: str, password: str,
                 mailbox: str = "INBOX", max_body_chars: int = 4000):
        self.name = name
        self.host = host
        self.user = user
        self.password = password
        self.mailbox = mailbox
        self.max_body_chars = max_body_chars

    @property
    def _is_gmail(self) -> bool:
        return self.host.endswith("gmail.com")

    def fetch(self, since: datetime) -> list[RawEmail]:
        conn = imaplib.IMAP4_SSL(self.host)
        try:
            conn.login(self.user, self.password)
            conn.select(self.mailbox, readonly=True)
            # IMAP SINCE has day granularity; filter precisely after parsing.
            typ, data = conn.search(None, "SINCE", since.strftime("%d-%b-%Y"))
            if typ != "OK":
                raise RuntimeError(f"IMAP search failed: {data!r}")
            ids = data[0].split()
            items = "(BODY.PEEK[] X-GM-THRID)" if self._is_gmail else "(BODY.PEEK[])"
            emails: list[RawEmail] = []
            for msg_id in ids:
                typ, resp = conn.fetch(msg_id, items)
                if typ != "OK" or not resp or not isinstance(resp[0], tuple):
                    continue
                meta, raw = resp[0]
                fields = parse_mime(raw, self.max_body_chars)
                if fields["received"] < since:
                    continue
                emails.append(RawEmail(account=self.name, link=self._link(meta), **fields))
            return emails
        finally:
            try:
                conn.logout()
            except Exception:
                pass

    def _link(self, meta: bytes) -> str:
        if not self._is_gmail:
            return ""
        m = _THRID_RE.search(meta)
        return f"https://mail.google.com/mail/u/0/#all/{int(m.group(1)):x}" if m else ""
