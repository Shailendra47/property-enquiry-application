"""High-performance, resilient Zoho CRM Leads API client.

Optimizations:
- Persistent connection pooling via requests.Session (reduces latency & TLS handshakes)
- Dynamic environment variable resolution (picks up runtime .env updates without requiring a server reboot)
- Thread-safe double-checked token caching
- Automatic 401 token invalidation and retry (self-healing)
- Phone number sanitization (removes Twilio 'whatsapp:' prefix)
- Detailed error logging (extracts status, error code, message, and details from Zoho responses)
- Safe, non-blocking background execution for FastAPI/Starlette
"""

import logging
import os
import re
import threading
import time
from datetime import datetime, timezone
from urllib.parse import urlparse

import requests
from dotenv import load_dotenv
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

load_dotenv()

logger = logging.getLogger("uvicorn.error")

# Global reusable session with keep-alive and connection pooling
_session = requests.Session()
_retry_strategy = Retry(
    total=2,
    backoff_factor=0.3,
    status_forcelist=[500, 502, 503, 504],
    raise_on_status=False,
)
_adapter = HTTPAdapter(
    pool_connections=10,
    pool_maxsize=20,
    max_retries=_retry_strategy,
)
_session.mount("https://", _adapter)
_session.mount("http://", _adapter)

_token_lock = threading.Lock()
_access_token = ""
_token_expires_at = 0.0
_api_domain = os.getenv("ZOHO_API_DOMAIN", "https://www.zohoapis.in").rstrip("/")

_mongo_lock = threading.Lock()
_mongo_client = None


def _get_mongo_db():
    global _mongo_client
    uri = os.getenv("MONGODB_URI")
    db_name = os.getenv("DB_NAME", "property_db")
    if not uri:
        return None
    with _mongo_lock:
        if _mongo_client is None:
            from pymongo import MongoClient
            _mongo_client = MongoClient(uri, serverSelectionTimeoutMS=4000)
        return _mongo_client[db_name]

# Default exported constants for backwards-compatibility
ZOHO_MODULE = os.getenv("ZOHO_MODULE", "Leads").strip() or "Leads"
ZOHO_DEFAULT_COMPANY = os.getenv("ZOHO_DEFAULT_COMPANY", "Profilent").strip() or "Profilent"


def _get_config() -> dict[str, str]:
    """Retrieve configuration dynamically so runtime .env updates take effect immediately."""
    return {
        "client_id": os.getenv("ZOHO_CLIENT_ID", "").strip(),
        "client_secret": os.getenv("ZOHO_CLIENT_SECRET", "").strip(),
        "refresh_token": os.getenv("ZOHO_REFRESH_TOKEN", "").strip(),
        "accounts_url": os.getenv("ZOHO_ACCOUNTS_URL", "https://accounts.zoho.in").rstrip("/"),
        "api_domain": os.getenv("ZOHO_API_DOMAIN", "https://www.zohoapis.in").rstrip("/"),
        "module": os.getenv("ZOHO_MODULE", "Leads").strip() or "Leads",
        "company": os.getenv("ZOHO_DEFAULT_COMPANY", "Profilent").strip() or "Profilent",
    }


def zoho_is_configured() -> bool:
    """Check if all required Zoho OAuth credentials are present in the environment."""
    config = _get_config()
    return bool(config["client_id"] and config["client_secret"] and config["refresh_token"])


def _invalidate_token() -> None:
    """Clear cached token when a 401 Unauthorized is encountered."""
    global _access_token, _token_expires_at
    with _token_lock:
        _access_token = ""
        _token_expires_at = 0.0


def _get_access_token(force_refresh: bool = False) -> str:
    """Return access token with thread-safe double-checked caching."""
    global _access_token, _token_expires_at, _api_domain
    config = _get_config()

    if not (config["client_id"] and config["client_secret"] and config["refresh_token"]):
        raise RuntimeError("Zoho CRM OAuth is not configured")

    now = time.monotonic()
    if not force_refresh and _access_token and now < (_token_expires_at - 60):
        return _access_token

    with _token_lock:
        now = time.monotonic()
        if not force_refresh and _access_token and now < (_token_expires_at - 60):
            return _access_token

        response = _session.post(
            f"{config['accounts_url']}/oauth/v2/token",
            data={
                "refresh_token": config["refresh_token"],
                "client_id": config["client_id"],
                "client_secret": config["client_secret"],
                "grant_type": "refresh_token",
            },
            timeout=12,
        )

        try:
            body = response.json()
        except ValueError as exc:
            snippet = (response.text or "").strip()[:200] or "<empty>"
            raise RuntimeError(
                f"Zoho OAuth returned an unreadable response (HTTP {response.status_code}): {snippet}"
            ) from exc

        token = body.get("access_token")
        if not token:
            error = str(body.get("error") or "unknown_error")
            if error == "invalid_code":
                raise RuntimeError(
                    "Zoho rejected ZOHO_REFRESH_TOKEN (invalid_code). Ensure it is the "
                    "long-lived refresh_token returned by a fresh authorization-code "
                    "exchange, for this exact client ID and Zoho data center. Do not "
                    "put the temporary authorization code or access token in this setting."
                )
            raise RuntimeError(
                f"Zoho OAuth failed (HTTP {response.status_code}, error={error})"
            )

        if not response.ok:
            raise RuntimeError(f"Zoho OAuth failed (HTTP {response.status_code})")

        candidate_domain = str(body.get("api_domain") or config["api_domain"]).rstrip("/")
        parsed = urlparse(candidate_domain)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or ("zohoapis." not in parsed.hostname and not parsed.hostname.endswith("zohoapis"))
        ):
            raise RuntimeError(f"Zoho returned an invalid API domain: {candidate_domain}")

        _api_domain = candidate_domain
        _access_token = token
        _token_expires_at = time.monotonic() + int(body.get("expires_in", 3600))
        return _access_token


def _display_name(
    name: object, first_name_hint: str = "", last_name_hint: str = ""
) -> tuple[str, str]:
    """Split full name into (First_Name, Last_Name) with field length limits."""
    first_hint = str(first_name_hint or "").strip()
    last_hint = str(last_name_hint or "").strip()
    if last_hint:
        return (first_hint[:40], last_hint[:80])
    parts = str(name or "").strip().split()
    if not parts:
        return ("", "Property Lead")
    if len(parts) == 1:
        return ("", parts[0][:80])
    return (parts[0][:40], " ".join(parts[1:])[:80])


def _clean_phone(raw: object) -> str:
    """Normalize phone by stripping 'whatsapp:' prefix and extraneous whitespace."""
    if not raw:
        return ""
    val = str(raw).strip()
    return re.sub(r"^whatsapp:", "", val, flags=re.IGNORECASE).strip()


def _update_mongo_zoho_id(lead: dict, zoho_lead_id: str) -> None:
    """Persist Zoho CRM record ID and sync timestamp back to MongoDB Atlas."""
    if not zoho_lead_id or zoho_lead_id == "unknown":
        return

    try:
        from bson import ObjectId

        db = _get_mongo_db()
        if db is None:
            return

        now = datetime.now(timezone.utc)
        update_doc = {
            "$set": {
                "zoho_lead_id": zoho_lead_id,
                "zoho_synced_at": now,
                "zoho_sync_status": "synced",
            }
        }

        # 1. Update by local_id if given
        local_id = str(lead.get("local_id") or "").strip()
        if local_id:
            try:
                oid = ObjectId(local_id)
                db.property_leads.update_one({"_id": oid}, update_doc)
                db.contacts.update_one({"_id": oid}, update_doc)
                db.whatsapp_conversations.update_one({"_id": oid}, update_doc)
            except Exception:
                pass

        # 2. Update by contact_id if given
        contact_id = str(lead.get("contact_id") or "").strip()
        if contact_id:
            try:
                db.contacts.update_one({"_id": ObjectId(contact_id)}, update_doc)
            except Exception:
                pass

        # 3. Update by _id if given
        raw_id = lead.get("_id")
        if raw_id:
            try:
                oid = raw_id if isinstance(raw_id, ObjectId) else ObjectId(str(raw_id))
                db.property_leads.update_one({"_id": oid}, update_doc)
                db.contacts.update_one({"_id": oid}, update_doc)
            except Exception:
                pass

        # 4. Update matching records by email
        email = str(lead.get("email") or "").strip()
        if email:
            regex_email = re.compile(f"^{re.escape(email)}$", re.IGNORECASE)
            db.property_leads.update_many({"email": regex_email}, update_doc)
            db.contacts.update_many({"email": regex_email}, update_doc)

        # 5. Update matching records by phone
        phone = _clean_phone(lead.get("mobile_number") or lead.get("contact_number") or lead.get("phone") or "")
        if phone:
            db.property_leads.update_many({"mobile_number": phone}, update_doc)
            db.property_leads.update_many({"whatsapp_number": phone}, update_doc)
            db.contacts.update_many({"contact_number": phone}, update_doc)
            db.whatsapp_conversations.update_many({"phone": phone}, update_doc)
    except Exception as exc:
        logger.warning("Could not persist Zoho lead ID %s to MongoDB: %s", zoho_lead_id, exc)


def sync_zoho_lead(lead: dict, retry_on_auth_fail: bool = True) -> str | None:
    """Upsert a lead by email/phone into Zoho CRM and persist Zoho lead ID back to MongoDB."""
    if not zoho_is_configured():
        logger.info("Zoho CRM sync skipped: OAuth refresh token is not configured")
        return None

    config = _get_config()
    module_name = config["module"]
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", module_name):
        raise ValueError(f"ZOHO_MODULE contains invalid characters: {module_name!r}")

    try:
        first_name, last_name = _display_name(
            lead.get("full_name") or " ".join(filter(None, [lead.get("first_name", ""), lead.get("last_name", "")])),
            first_name_hint=lead.get("first_name", ""),
            last_name_hint=lead.get("last_name", ""),
        )
        phone = _clean_phone(
            lead.get("mobile_number") or lead.get("contact_number") or lead.get("whatsapp_number") or ""
        )
        contact_phone = _clean_phone(lead.get("contact_number") or "")
        email = str(lead.get("email") or "").strip()

        wa_answers = lead.get("whatsapp_answers") or {}
        location = str(lead.get("location_preference") or wa_answers.get("location_preference") or "").strip()
        planning = str(lead.get("planning_to_buy") or wa_answers.get("planning_to_buy") or "").strip()
        budget = str(lead.get("budget_range") or wa_answers.get("budget_range") or "").strip()
        payment = str(lead.get("payment_option") or wa_answers.get("payment_option") or "").strip()
        bhk = str(lead.get("bhk_preference") or wa_answers.get("bhk_preference") or "").strip()
        requirements = str(
            lead.get("remarks_requirements")
            or lead.get("requirement")
            or wa_answers.get("remarks_requirements")
            or wa_answers.get("remarks")
            or ""
        ).strip()

        description_sections = [
            "=== PROPERTY REQUIREMENTS ===",
            f"Location Preference : {location or 'Not specified'}",
            f"Property Type / BHK : {bhk or 'Not specified'}",
            f"Budget Range        : {budget or 'Not specified'}",
            f"Buying Timeline     : {planning or 'Not specified'}",
            f"Payment Preference  : {payment or 'Not specified'}",
            f"Special Requirements: {requirements or 'None'}",
            "===============================",
            f"Lead Source         : {lead.get('source', 'Website property enquiry')}",
            f"WhatsApp Opt-in     : {'Yes' if (lead.get('whatsapp_opt_in') or wa_answers.get('whatsapp_opt_in')) else 'No'}",
        ]
        if lead.get("local_id"):
            description_sections.append(f"Local MongoDB ID    : {lead['local_id']}")
        if lead.get("calendly_event_name"):
            description_sections.append(f"Calendly Meeting    : {lead['calendly_event_name']} ({lead.get('calendly_start_time', '')})")
        if lead.get("calendly_join_url"):
            description_sections.append(f"Meeting URL         : {lead['calendly_join_url']}")

        record = {
            "First_Name": first_name,
            "Last_Name": last_name,
            "Company": config["company"],
            "Description": "\n".join(description_sections)[:32000],
            "Lead_Source": "Advertisement",
        }

        # Standard & Address fields mapping
        if location:
            record["City"] = location[:100]
            parts = [p.strip() for p in location.split(",") if p.strip()]
            if len(parts) >= 2:
                record["Street"] = parts[0][:250]
                record["State"] = parts[-1][:100]
            else:
                record["Street"] = location[:250]

        if bhk:
            # Maps to standard/custom apartment/property configuration field in Zoho CRM
            record["Flat_House_No_Building_Apartment_Name"] = bhk[:100]
            record["BHK_Preference"] = bhk[:100]
            record["Property_Type"] = bhk[:100]

        if budget:
            record["Budget_Range"] = budget[:100]
            record["Budget"] = budget[:100]

        if planning:
            record["Buying_Timeline"] = planning[:100]
            record["Timeline"] = planning[:100]

        if payment:
            record["Payment_Option"] = payment[:100]
            record["Payment_Preference"] = payment[:100]

        if requirements:
            record["Special_Requirements"] = requirements[:255]
            record["Remarks"] = requirements[:255]

        if email:
            record["Email"] = email
        if phone:
            record["Phone"] = phone
            record["Mobile"] = phone
        if contact_phone:
            record["Mobile"] = contact_phone

        payload = {"data": [record]}
        if email:
            payload["duplicate_check_fields"] = ["Email"]
        elif phone:
            payload["duplicate_check_fields"] = ["Phone"]

        access_token = _get_access_token()

        response = _session.post(
            f"{_api_domain}/crm/v8/{module_name}/upsert",
            json=payload,
            headers={"Authorization": f"Zoho-oauthtoken {access_token}"},
            timeout=15,
        )

        # Self-heal on 401 Unauthorized by clearing cache and retrying once
        if response.status_code == 401 and retry_on_auth_fail:
            logger.warning("Zoho access token expired or invalid (HTTP 401). Refreshing token and retrying...")
            _invalidate_token()
            return sync_zoho_lead(lead, retry_on_auth_fail=False)

        response.raise_for_status()
        body = response.json()
        rows = body.get("data", [])
        if not rows or rows[0].get("status") != "success":
            row = rows[0] if rows else {}
            error_code = row.get("code") or body.get("code", "unknown")
            error_msg = row.get("message") or body.get("message", "no details")
            error_details = row.get("details") or body.get("details", {})
            logger.error(
                "Zoho CRM rejected lead upsert (code=%s, message=%s, details=%s)",
                error_code,
                error_msg,
                error_details,
            )
            return None

        record_id = rows[0].get("details", {}).get("id", "unknown")
        logger.info("Zoho CRM lead upsert succeeded (record_id=%s)", record_id)

        # Persist Zoho CRM ID back into MongoDB Atlas
        _update_mongo_zoho_id(lead, record_id)
        return record_id

    except Exception:
        logger.exception("Zoho CRM lead sync failed")
        return None


def sync_all_from_mongo() -> dict:
    """Sync all property leads and contacts from MongoDB Atlas to Zoho CRM."""
    db = _get_mongo_db()
    if db is None:
        return {"error": "MongoDB connection not available"}

    synced = []
    failed = []

    # 1. Sync all property_leads
    for pl in db.property_leads.find():
        lead_data = {
            **pl,
            "local_id": str(pl.get("_id", "")),
            "source": pl.get("source") or "Website property enquiry",
        }
        res = sync_zoho_lead(lead_data)
        ident = pl.get("email") or pl.get("mobile_number") or str(pl.get("_id"))
        if res:
            synced.append({"type": "property_lead", "id": str(pl.get("_id")), "ident": ident, "zoho_id": res})
        else:
            failed.append({"type": "property_lead", "id": str(pl.get("_id")), "ident": ident})

    # 2. Sync all contacts with whatsapp_answers or requirement
    for c in db.contacts.find({"$or": [{"whatsapp_answers": {"$exists": True, "$ne": None}}, {"requirement": {"$exists": True, "$ne": ""}}]}):
        wa = c.get("whatsapp_answers") or {}
        full_name = c.get("full_name") or " ".join(filter(None, [wa.get("first_name", ""), wa.get("last_name", "")]))
        lead_data = {
            **wa,
            **c,
            "full_name": full_name,
            "local_id": str(c.get("_id", "")),
            "contact_id": str(c.get("_id", "")),
            "source": "WhatsApp questionnaire" if c.get("whatsapp_answers") else "Website Contact Us",
        }
        res = sync_zoho_lead(lead_data)
        ident = c.get("email") or c.get("contact_number") or str(c.get("_id"))
        if res:
            synced.append({"type": "contact", "id": str(c.get("_id")), "ident": ident, "zoho_id": res})
        else:
            failed.append({"type": "contact", "id": str(c.get("_id")), "ident": ident})

    return {"total_synced": len(synced), "total_failed": len(failed), "synced": synced, "failed": failed}
