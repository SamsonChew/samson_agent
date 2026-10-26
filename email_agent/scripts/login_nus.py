"""One-time NUS (Microsoft 365) login: prints a refresh token to store as the NUS_REFRESH_TOKEN secret.

Usage (on your own computer):
    pip install msal
    NUS_CLIENT_ID=<your Azure app client id> python -m email_agent.scripts.login_nus
"""

from __future__ import annotations

import os
import sys

import msal

SCOPES = ["Mail.Read"]  # MSAL adds offline_access / openid / profile automatically


def main() -> int:
    client_id = os.environ.get("NUS_CLIENT_ID") or input("Azure app (client) ID: ").strip()
    tenant = os.environ.get("NUS_TENANT", "organizations")
    app = msal.PublicClientApplication(client_id, authority=f"https://login.microsoftonline.com/{tenant}")

    flow = app.initiate_device_flow(scopes=SCOPES)
    if "user_code" not in flow:
        print(f"Could not start device flow: {flow}", file=sys.stderr)
        return 1
    print(flow["message"])  # "To sign in, open https://microsoft.com/devicelogin and enter code XXXX"

    result = app.acquire_token_by_device_flow(flow)
    if "refresh_token" not in result:
        print(f"\nLogin failed: {result.get('error')}: {result.get('error_description')}", file=sys.stderr)
        if "AADSTS65001" in str(result) or "admin" in str(result.get("error_description", "")).lower():
            print("NUS requires admin approval for this app. See email_agent/README.md -> 'Plan B: forward to Gmail'.",
                  file=sys.stderr)
        return 1

    who = (result.get("id_token_claims") or {}).get("preferred_username", "?")
    print(f"\nLogged in as {who}.")
    print("Add this as the GitHub secret NUS_REFRESH_TOKEN:\n")
    print(result["refresh_token"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
