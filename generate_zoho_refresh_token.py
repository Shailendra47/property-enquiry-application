"""Helper script to exchange a Zoho temporary authorization code for a long-lived refresh token.

Usage:
    python generate_zoho_refresh_token.py [code]
"""

import os
import sys
from pathlib import Path
import requests
from dotenv import load_dotenv

ENV_FILE = Path(__file__).resolve().parent / ".env"
load_dotenv(ENV_FILE)

ZOHO_CLIENT_ID = os.getenv("ZOHO_CLIENT_ID", "").strip()
ZOHO_CLIENT_SECRET = os.getenv("ZOHO_CLIENT_SECRET", "").strip()
ZOHO_ACCOUNTS_URL = os.getenv("ZOHO_ACCOUNTS_URL", "https://accounts.zoho.in").rstrip("/")
ZOHO_REDIRECT_URI = os.getenv("ZOHO_REDIRECT_URI", "").strip()


def main():
    if not ZOHO_CLIENT_ID or not ZOHO_CLIENT_SECRET:
        print("Error: ZOHO_CLIENT_ID and ZOHO_CLIENT_SECRET must be set in .env")
        return 1

    code = ""
    redirect_uri = ZOHO_REDIRECT_URI
    if len(sys.argv) > 1:
        code = sys.argv[1].strip()
    if len(sys.argv) > 2:
        redirect_uri = sys.argv[2].strip()

    if not code:
        code = input("Enter the temporary code from Zoho API Console (Self Client): ").strip()

    if not code:
        print("Error: No code provided.")
        return 1

    print(f"Exchanging code with {ZOHO_ACCOUNTS_URL}/oauth/v2/token ...")
    payload = {
        "client_id": ZOHO_CLIENT_ID,
        "client_secret": ZOHO_CLIENT_SECRET,
        "grant_type": "authorization_code",
        "code": code,
    }
    if redirect_uri:
        payload["redirect_uri"] = redirect_uri

    try:
        response = requests.post(
            f"{ZOHO_ACCOUNTS_URL}/oauth/v2/token",
            data=payload,
            timeout=15,
        )
    except Exception as exc:
        print(f"Request error: {exc}")
        return 1

    try:
        body = response.json()
    except Exception:
        print(f"Failed to parse response (HTTP {response.status_code}): {response.text}")
        return 1

    if "error" in body:
        print(f"\nZoho rejected the code: {body.get('error')}")
        print("Reasons for 'invalid_code':")
        print(" 1. The code expired (Zoho grant codes expire within 2 to 10 minutes).")
        print(" 2. The code was generated with different client credentials than ZOHO_CLIENT_ID in .env.")
        print(" 3. If your client is a 'Server-based Application', you must also pass the registered redirect_uri:")
        print("    python generate_zoho_refresh_token.py <code> <redirect_uri>")
        return 1

    refresh_token = body.get("refresh_token")
    access_token = body.get("access_token")

    if not refresh_token:
        print("\nNo refresh_token returned in response. Full response:")
        print(body)
        print("\nNote: Zoho only returns a refresh_token on the first exchange for a code.")
        return 1

    print("\nSUCCESS! Successfully generated refresh token:")
    print(f"Refresh Token: {refresh_token}")

    # Update .env automatically
    if ENV_FILE.exists():
        content = ENV_FILE.read_text(encoding="utf-8")
        import re
        if re.search(r"^ZOHO_REFRESH_TOKEN=.*$", content, flags=re.MULTILINE):
            new_content = re.sub(
                r"^ZOHO_REFRESH_TOKEN=.*$",
                f"ZOHO_REFRESH_TOKEN={refresh_token}",
                content,
                flags=re.MULTILINE,
            )
        else:
            new_content = content + f"\nZOHO_REFRESH_TOKEN={refresh_token}\n"
        ENV_FILE.write_text(new_content, encoding="utf-8")
        print("\nUpdated ZOHO_REFRESH_TOKEN in .env successfully.")

    print("\nNow run check_zoho_connection.py to verify:")
    print("python check_zoho_connection.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())

