"""NUS mailbox (Microsoft 365) via Microsoft Graph, authenticated with a delegated refresh token."""

from __future__ import annotations

from datetime import datetime, timezone

import msal
import requests

from ..parser import clean_body, html_to_text, is_bulk, parse_date
from .base import RawEmail

GRAPH = "https://graph.microsoft.com/v1.0"
SCOPES = ["Mail.Read"]
_SELECT = "id,internetMessageId,subject,from,receivedDateTime,body,webLink,internetMessageHeaders"


class GraphAuthError(RuntimeError):
    """Refresh token rejected — run email_agent/scripts/login_nus.py again."""


def acquire_token(client_id: str, refresh_token: str, tenant: str = "organizations") -> str:
    app = msal.PublicClientApplication(client_id, authority=f"https://login.microsoftonline.com/{tenant}")
    result = app.acquire_token_by_refresh_token(refresh_token, scopes=SCOPES)
    if "access_token" not in result:
        raise GraphAuthError(
            f"NUS login expired or was revoked ({result.get('error')}): "
            "re-run `python -m email_agent.scripts.login_nus` and update NUS_REFRESH_TOKEN."
        )
    return result["access_token"]


def to_raw_email(msg: dict, account: str, max_body_chars: int) -> RawEmail:
    body = msg.get("body") or {}
    content = body.get("content", "")
    if body.get("contentType", "").lower() == "html":
        content = html_to_text(content)
    sender = (msg.get("from") or {}).get("emailAddress") or {}
    name, addr = sender.get("name", ""), sender.get("address", "")
    return RawEmail(
        account=account,
        message_id=msg.get("internetMessageId", "") or msg.get("id", ""),
        subject=msg.get("subject") or "(no subject)",
        sender=f"{name} <{addr}>" if name else addr,
        received=_parse_graph_dt(msg.get("receivedDateTime")),
        body=clean_body(content, max_body_chars),
        link=msg.get("webLink", ""),
        bulk=is_bulk({h["name"]: h.get("value", "") for h in msg.get("internetMessageHeaders") or []}),
    )


def _parse_graph_dt(value: str | None) -> datetime:
    if not value:
        return parse_date(None)
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


class GraphSource:
    def __init__(self, name: str, client_id: str, refresh_token: str,
                 tenant: str = "organizations", max_body_chars: int = 4000):
        self.name = name
        self.client_id = client_id
        self.refresh_token = refresh_token
        self.tenant = tenant
        self.max_body_chars = max_body_chars

    def fetch(self, since: datetime) -> list[RawEmail]:
        token = acquire_token(self.client_id, self.refresh_token, self.tenant)
        headers = {
            "Authorization": f"Bearer {token}",
            "Prefer": 'outlook.body-content-type="text"',
        }
        since_iso = since.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        url = f"{GRAPH}/me/mailFolders/inbox/messages"
        params: dict | None = {
            "$filter": f"receivedDateTime ge {since_iso}",
            "$select": _SELECT,
            "$orderby": "receivedDateTime desc",
            "$top": "50",
        }
        emails: list[RawEmail] = []
        while url:
            resp = requests.get(url, headers=headers, params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            emails.extend(to_raw_email(m, self.name, self.max_body_chars) for m in data.get("value", []))
            url, params = data.get("@odata.nextLink"), None  # nextLink already carries the query
        return emails
