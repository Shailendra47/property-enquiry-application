"""Small, optional Zoho CRM Leads API client.

All network calls are synchronous so FastAPI BackgroundTasks can run them off
the request path. Authentication uses a refresh token; short-lived grant codes
are deliberately not stored in application code.
"""

import logging
import os
import re
import threading
import time
from urllib.parse import urlparse

import requests

logger = logging.getLogger("uvicorn.error")

ZOHO_CLIENT_ID = os.getenv("ZOHO_CLIENT_ID", "").strip()
ZOHO_CLIENT_SECRET = os.getenv("ZOHO_CLIENT_SECRET", "").strip()
ZOHO_REFRESH_TOKEN = os.getenv("ZOHO_REFRESH_TOKEN", "").strip()
ZOHO_ACCOUNTS_URL = os.getenv("ZOHO_ACCOUNTS_URL", "https://accounts.zoho.in").rstrip("/")
ZOHO_API_DOMAIN = os.getenv("ZOHO_API_DOMAIN", "https://www.zohoapis.in").rstrip("/")
ZOHO_MODULE = os.getenv("ZOHO_MODULE", "Leads").strip()
ZOHO_DEFAULT_COMPANY = os.getenv("ZOHO_DEFAULT_COMPANY", "Profilent").strip() or "Profilent"

_token_lock = threading.Lock()
_access_token = ""
_token_expires_at = 0.0
_api_domain = ZOHO_API_DOMAIN


def zoho_is_configured() -> bool:
    return bool(ZOHO_CLIENT_ID and ZOHO_CLIENT_SECRET and ZOHO_REFRESH_TOKEN)


def _get_access_token() -> str:
    global _access_token, _token_expires_at, _api_domain
    if not zoho_is_configured():
        raise RuntimeError("Zoho CRM OAuth is not configured")

    with _token_lock:
        if _access_token and time.monotonic() < _token_expires_at - 60:
            return _access_token

        response = requests.post(
            f"{ZOHO_ACCOUNTS_URL}/oauth/v2/token",
            data={
                "refresh_token": ZOHO_REFRESH_TOKEN,
                "client_id": ZOHO_CLIENT_ID,
                "client_secret": ZOHO_CLIENT_SECRET,
                "grant_type": "refresh_token",
            },
            timeout=12,
        )
        response.raise_for_status()
        body = response.json()
        token = body.get("access_token")
        if not token:
            raise RuntimeError(f"Zoho token response did not include an access token: {body.get('error', 'unknown error')}")

        candidate_domain = str(body.get("api_domain") or _api_domain).rstrip("/")
        parsed = urlparse(candidate_domain)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or ("zohoapis." not in parsed.hostname and not parsed.hostname.endswith("zohoapis"))
        ):
            raise RuntimeError("Zoho returned an invalid API domain")
        _api_domain = candidate_domain
        _access_token = token
        _token_expires_at = time.monotonic() + int(body.get("expires_in", 3600))
        return _access_token


def _display_name(name: object) -> tuple[str, str]:
    parts = str(name or "").strip().split()
    return (" ".join(parts[:-1])[:40], (parts[-1] if parts else "Unknown")[:80])


def sync_zoho_lead(lead: dict) -> None:
    """Upsert a lead by email/phone; failures are logged without affecting the form."""
    if not zoho_is_configured():
        logger.info("Zoho CRM sync skipped: OAuth refresh token is not configured")
        return

    try:
        first_name, last_name = _display_name(
            lead.get("full_name") or " ".join((lead.get("first_name", ""), lead.get("last_name", "")))
        )
        phone = str(lead.get("mobile_number") or lead.get("contact_number") or lead.get("whatsapp_number") or "").strip()
        email = str(lead.get("email") or "").strip()
        description_lines = [
            f"Lead source: {lead.get('source', 'Website')}",
            f"Location: {lead.get('location_preference', '')}",
            f"Buying timeline: {lead.get('planning_to_buy', '')}",
            f"Budget: {lead.get('budget_range', '')}",
            f"Payment preference: {lead.get('payment_option', '')}",
            f"Property type: {lead.get('bhk_preference', '')}",
            f"Requirements: {lead.get('remarks_requirements') or lead.get('requirement') or ''}",
            f"WhatsApp opt-in: {'Yes' if lead.get('whatsapp_opt_in') else 'No / not recorded'}",
            f"Local enquiry ID: {lead.get('local_id', '')}",
            f"Calendly meeting: {lead.get('calendly_event_name', '')}",
            f"Calendly date/time: {lead.get('calendly_start_time', '')}",
            f"Calendly meeting link: {lead.get('calendly_join_url', '')}",
        ]
        record = {
            "First_Name": first_name,
            "Last_Name": last_name,
            "Company": ZOHO_DEFAULT_COMPANY,
            "Description": "\n".join(line for line in description_lines if not line.endswith(": "))[:32000],
        }
        if email:
            record["Email"] = email
        if phone:
            record["Phone"] = phone
            record["Mobile"] = phone
        if lead.get("contact_number"):
            record["Mobile"] = str(lead["contact_number"])

        payload = {"data": [record]}
        # Email is Zoho's supported unique lead key by default. Phone is not
        # guaranteed to be configured as a unique field in every CRM layout.
        if email:
            payload["duplicate_check_fields"] = ["Email"]

        module_name = ZOHO_MODULE
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", module_name):
            raise ValueError("ZOHO_MODULE contains invalid characters")
        response = requests.post(
            f"{_api_domain}/crm/v8/{module_name}/upsert",
            json=payload,
            headers={"Authorization": f"Zoho-oauthtoken {_get_access_token()}"},
            timeout=15,
        )
        response.raise_for_status()
        body = response.json()
        rows = body.get("data", [])
        if not rows or rows[0].get("status") != "success":
            error_code = rows[0].get("code", "unknown") if rows else body.get("code", "unknown")
            logger.error("Zoho CRM rejected lead upsert (code=%s)", error_code)
            return
        logger.info("Zoho CRM lead upsert succeeded (record_id=%s)", rows[0].get("details", {}).get("id", "unknown"))
    except Exception:
        logger.exception("Zoho CRM lead sync failed")
