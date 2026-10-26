"""Run a safe, read-only Zoho CRM connection check using the local .env."""

import re
import sys

import requests
from dotenv import load_dotenv

load_dotenv()

import zoho_crm


def main() -> int:
    try:
        access_token = zoho_crm._get_access_token()
    except Exception as exc:
        print(f"OAuth refresh failed: {exc}")
        return 1

    module = zoho_crm.ZOHO_MODULE
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", module):
        print("CRM check failed: ZOHO_MODULE contains invalid characters")
        return 1

    print("OAuth refresh succeeded.")
    try:
        response = requests.get(
            f"{zoho_crm._api_domain}/crm/v8/{module}",
            params={"per_page": 1, "fields": "id"},
            headers={"Authorization": f"Zoho-oauthtoken {access_token}"},
            timeout=15,
        )
    except requests.RequestException as exc:
        print(f"CRM read-only request failed: {type(exc).__name__}")
        return 1

    try:
        payload = response.json()
    except ValueError:
        payload = {}

    if response.ok and "data" in payload:
        print(f"CRM read-only request succeeded (HTTP {response.status_code}, module={module}).")
        print("No CRM records were created or changed.")
        return 0

    error_code = payload.get("code", "unrecognized_response")
    print(f"CRM read-only request failed (HTTP {response.status_code}, code={error_code}).")
    print("No CRM records were created or changed.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
