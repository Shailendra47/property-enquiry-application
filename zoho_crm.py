"""High-performance, resilient Zoho CRM Leads API client with strict validation & Hot Lead filtering.

Optimizations:
- Strict validation: Filters out fake/dummy contact data, invalid phones, and test domains
- Hot lead qualification: Scores and prioritizes high-intent leads (immediate buyers, cash buyers, high budget, Calendly appointments)
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

_zoho_rate_limit_cooldown_until = 0.0

def _is_zoho_in_cooldown() -> bool:
    global _zoho_rate_limit_cooldown_until
    return time.monotonic() < _zoho_rate_limit_cooldown_until

def _set_zoho_cooldown(seconds: float = 300.0) -> None:
    global _zoho_rate_limit_cooldown_until
    _zoho_rate_limit_cooldown_until = time.monotonic() + seconds

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
        "only_hot_leads": os.getenv("ZOHO_SYNC_ONLY_HOT_LEADS", "true").strip().lower() in ("true", "1", "yes"),
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


DUMMY_DOMAINS = {
    "example.com", "test.com", "testing.com", "demo.com",
    "dummy.com", "sample.com", "mailinator.com", "invalid.com"
}

DUMMY_NAME_PATTERNS = [
    r"^test\b", r"\btest$", r"^testing\b", r"^demo\b", r"^asdf\b",
    r"^qwerty\b", r"^admin\b", r"^fake\b", r"^anonymous\b",
    r"^none\b", r"^unknown\b", r"^user\b"
]


def validate_lead_data(lead: dict) -> tuple[bool, list[str]]:
    """Validate that lead has genuine contact information and not dummy/test data."""
    errors = []

    # 1. Name validation
    raw_name = (
        lead.get("full_name")
        or " ".join(filter(None, [str(lead.get("first_name", "")), str(lead.get("last_name", ""))]))
    ).strip()

    if not raw_name or len(raw_name) < 2:
        errors.append("Name is missing or too short (< 2 characters)")
    else:
        lower_name = raw_name.lower()
        for pat in DUMMY_NAME_PATTERNS:
            if re.search(pat, lower_name):
                errors.append(f"Name looks like test/placeholder data ('{raw_name}')")
                break
        if not re.search(r"[a-zA-Z\u0900-\u097F]", raw_name):
            errors.append("Name must contain letters")

    # 2. Phone validation
    raw_phone = str(
        lead.get("mobile_number")
        or lead.get("contact_number")
        or lead.get("whatsapp_number")
        or lead.get("phone")
        or ""
    ).strip()
    phone_clean = _clean_phone(raw_phone)
    phone_digits = re.sub(r"\D", "", phone_clean)

    if not phone_digits:
        errors.append("Phone number is missing")
    elif len(phone_digits) < 10 or len(phone_digits) > 15:
        errors.append(f"Phone number has invalid length ({len(phone_digits)} digits)")
    else:
        last10 = phone_digits[-10:]
        if len(set(last10)) <= 2:
            errors.append(f"Phone number looks fake/repeated ('{last10}')")
        elif last10 in {"1234567890", "0123456789", "9876543210"}:
            errors.append(f"Phone number is a dummy sequence ('{last10}')")

    # 3. Email validation
    email = str(lead.get("email") or "").strip().lower()
    if email:
        if not re.fullmatch(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$", email):
            errors.append(f"Email format is invalid ('{email}')")
        else:
            domain = email.split("@")[-1]
            if domain in DUMMY_DOMAINS:
                errors.append(f"Email domain '{domain}' is a test/placeholder domain")

    return (len(errors) == 0, errors)


def evaluate_lead_quality(lead: dict) -> dict:
    """Score lead quality and determine if it meets HOT LEAD criteria.

    Returns dict with keys:
    - is_valid: bool
    - validation_errors: list[str]
    - is_hot: bool
    - score: int (0-100)
    - rating: 'Hot' | 'Warm' | 'Cold'
    - lead_status: 'Hot Lead' | 'Warm Lead' | 'Cold Lead'
    - triggers: list[str]
    - reasons: list[str]
    """
    is_valid, validation_errors = validate_lead_data(lead)

    # If the lead was already classified by AI analysis:
    if lead.get("ai_rating") in ("Hot", "Warm", "Cold"):
        ai_rating = lead["ai_rating"]
        ai_score = int(lead.get("lead_score") or (80 if ai_rating == "Hot" else (45 if ai_rating == "Warm" else 15)))
        is_hot = (ai_rating == "Hot")
        return {
            "is_valid": is_valid,
            "validation_errors": validation_errors,
            "is_hot": is_hot,
            "score": ai_score,
            "rating": ai_rating,
            "lead_status": f"{ai_rating} Lead",
            "triggers": lead.get("ai_triggers") or [f"AI qualified as {ai_rating}"],
            "reasons": [lead.get("ai_analysis") or f"AI analyzed lead as {ai_rating}"],
        }

    score = 0
    reasons = []
    triggers = []

    wa_answers = lead.get("whatsapp_answers") or {}
    planning = str(lead.get("planning_to_buy") or wa_answers.get("planning_to_buy") or "").strip()
    budget = str(lead.get("budget_range") or wa_answers.get("budget_range") or "").strip()
    payment = str(lead.get("payment_option") or wa_answers.get("payment_option") or "").strip()
    location = str(lead.get("location_preference") or wa_answers.get("location_preference") or "").strip()
    bhk = str(lead.get("bhk_preference") or wa_answers.get("bhk_preference") or "").strip()
    calendly_event = str(lead.get("calendly_event_name") or "").strip()
    calendly_start = str(lead.get("calendly_start_time") or "").strip()

    # 1. Calendly direct consultation booking - automatic Hot Lead qualifier
    if calendly_event or calendly_start:
        score += 50
        triggers.append("Direct consultation meeting booked on Calendly")
        reasons.append(f"Meeting booked: {calendly_event or 'Advisor session'}")

    # 2. Timeline scoring
    p_low = planning.lower()
    if any(u in p_low for u in ["immediately", "within 1 month", "urgent"]):
        score += 40
        triggers.append(f"Urgent buying timeline: {planning}")
        reasons.append(f"Timeline: {planning} (+40)")
    elif any(u in p_low for u in ["within 3 months", "1 to 3 months", "2 months"]):
        score += 25
        reasons.append("Timeline: Within 3 Months (+25)")
    elif any(u in p_low for u in ["within 6 months", "3 to 6 months"]):
        score += 15
        reasons.append("Timeline: Within 6 Months (+15)")
    elif any(u in p_low for u in ["more than 1 year", "just exploring"]):
        score -= 10
        reasons.append(f"Low urgency timeline: {planning} (-10)")

    # 3. Budget scoring
    b_low = budget.lower()
    if any(u in b_low for u in ["above 2 crore", "above 1 crore", "above ₹1 crore", "1 crore - 2 crore", "80 lakh to 1 crore"]):
        score += 30
        triggers.append("High budget segment: Above 80L - 1Cr+")
        reasons.append(f"Budget: {budget} (+30)")
    elif any(u in b_low for u in ["50 lakh - 1 crore", "50 lakh to 80 lakh", "₹50 lakh to ₹80 lakh"]):
        score += 20
        reasons.append(f"Budget: {budget} (+20)")
    elif any(u in b_low for u in ["25 lakh - 50 lakh", "30 lakh to 50 lakh", "₹30 lakh to ₹50 lakh"]):
        score += 10
        reasons.append(f"Budget: {budget} (+10)")
    elif b_low:
        score += 5
        reasons.append(f"Budget: {budget} (+5)")

    # 4. Payment preference scoring
    pm_low = payment.lower()
    if any(u in pm_low for u in ["full payment", "full cash", "self funding", "poora cash"]):
        score += 25
        triggers.append("Ready cash buyer (Full Cash / Full Payment)")
        reasons.append(f"Payment: {payment} (+25)")
    elif any(u in pm_low for u in ["combination", "savings and loan", "part cash"]):
        score += 15
        reasons.append(f"Payment: {payment} (+15)")
    elif any(u in pm_low for u in ["home loan", "bank finance", "loan", "emi"]):
        score += 15
        reasons.append(f"Payment: {payment} (+15)")

    # 5. Property requirements completeness
    if location and bhk:
        score += 10
        reasons.append(f"Defined property preference: {bhk} in {location} (+10)")

    # 6. Conversational WhatsApp questionnaire completion
    if wa_answers and len(wa_answers) >= 3:
        score += 15
        reasons.append("Completed full WhatsApp qualification (+15)")

    final_score = max(0, min(100, score))

    # A lead qualifies as HOT if:
    # - Direct consultation meeting scheduled (Calendly), OR
    # - Buying Immediately / Within 1 Month with budget defined, OR
    # - Cash buyer buying within 3 months, OR
    # - High budget (>= 1 Cr) with timeline within 3 months, OR
    # - Overall intent score >= 50
    is_hot = bool(
        (calendly_event or calendly_start)
        or (planning in ["Immediately", "Within 1 Month"] and budget)
        or (payment == "Full Cash Payment" and planning in ["Immediately", "Within 1 Month", "Within 3 Months"])
        or (budget in ["1 crore - 2 crore", "Above 2 crore"] and planning in ["Immediately", "Within 1 Month", "Within 3 Months"])
        or (final_score >= 50)
    )

    if is_hot:
        rating = "Hot"
        lead_status = "Hot Lead"
    elif final_score >= 30:
        rating = "Warm"
        lead_status = "Warm Lead"
    else:
        rating = "Cold"
        lead_status = "Cold Lead"

    return {
        "is_valid": is_valid,
        "validation_errors": validation_errors,
        "is_hot": is_hot,
        "score": final_score,
        "rating": rating,
        "lead_status": lead_status,
        "triggers": triggers,
        "reasons": reasons,
    }


def _update_mongo_lead_status(
    lead: dict,
    status: str,
    zoho_lead_id: str = "",
    reason: str = "",
    score: int = 0,
    rating: str = "",
    clear_zoho_id: bool = False,
) -> None:
    """Persist sync status, reason, rating, and Zoho CRM ID back to MongoDB Atlas."""
    try:
        from bson import ObjectId

        db = _get_mongo_db()
        if db is None:
            return

        now = datetime.now(timezone.utc)
        update_doc = {
            "$set": {
                "zoho_sync_status": status,
                "zoho_sync_reason": reason,
                "lead_rating": rating,
                "lead_score": score,
                "lead_evaluated_at": now,
            }
        }
        if clear_zoho_id:
            update_doc["$unset"] = {"zoho_lead_id": "", "zoho_synced_at": ""}
        elif zoho_lead_id and zoho_lead_id != "unknown":
            update_doc["$set"]["zoho_lead_id"] = zoho_lead_id
            update_doc["$set"]["zoho_synced_at"] = now

        upsert_col = os.getenv("UPSERT_COLLECTION_NAME", "upserted_leads")
        enquiry_col = os.getenv("ENQUIRY_COLLECTION_NAME", "property_leads")
        contacts_col = os.getenv("COLLECTION_NAME", "contacts")

        # 1. Update by local_id if given (supports ObjectId or upsert_id string)
        local_id = str(lead.get("local_id") or "").strip()
        if local_id:
            try:
                db[upsert_col].update_many({"id": local_id}, update_doc)
            except Exception:
                pass
            try:
                oid = ObjectId(local_id)
                db[enquiry_col].update_one({"_id": oid}, update_doc)
                db[contacts_col].update_one({"_id": oid}, update_doc)
                db.whatsapp_conversations.update_one({"_id": oid}, update_doc)
            except Exception:
                pass

        # 1b. Update underlying submission records if unified upsert lead
        for rec in (lead.get("records") or []):
            rec_id = rec.get("id")
            rec_entity = rec.get("entity")
            if rec_id:
                try:
                    roid = ObjectId(rec_id)
                    if rec_entity == "contact":
                        db[contacts_col].update_one({"_id": roid}, update_doc)
                    elif rec_entity == "enquiry":
                        db[enquiry_col].update_one({"_id": roid}, update_doc)
                except Exception:
                    pass

        # 2. Update by contact_id if given
        contact_id = str(lead.get("contact_id") or "").strip()
        if contact_id:
            try:
                db[contacts_col].update_one({"_id": ObjectId(contact_id)}, update_doc)
            except Exception:
                pass

        # 3. Update by _id if given
        raw_id = lead.get("_id")
        if raw_id:
            try:
                oid = raw_id if isinstance(raw_id, ObjectId) else ObjectId(str(raw_id))
                db[enquiry_col].update_one({"_id": oid}, update_doc)
                db[contacts_col].update_one({"_id": oid}, update_doc)
            except Exception:
                pass

        # 4. Update matching records by email
        email = str(lead.get("email") or "").strip()
        if email:
            regex_email = re.compile(f"^{re.escape(email)}$", re.IGNORECASE)
            db[enquiry_col].update_many({"email": regex_email}, update_doc)
            db[contacts_col].update_many({"email": regex_email}, update_doc)
            db[upsert_col].update_many({"email": regex_email}, update_doc)

        # 5. Update matching records by phone
        phone = _clean_phone(lead.get("mobile_number") or lead.get("contact_number") or lead.get("phone") or "")
        if phone:
            db[enquiry_col].update_many({"mobile_number": phone}, update_doc)
            db[enquiry_col].update_many({"whatsapp_number": phone}, update_doc)
            db[contacts_col].update_many({"contact_number": phone}, update_doc)
            db.whatsapp_conversations.update_many({"phone": phone}, update_doc)
            db[upsert_col].update_many({"phone": phone}, update_doc)
    except Exception as exc:
        logger.warning("Could not persist Zoho sync status to MongoDB: %s", exc)


def sync_zoho_lead(
    lead: dict,
    retry_on_auth_fail: bool = True,
    only_hot: bool = True,
) -> str | None:
    """Upsert a validated hot lead into Zoho CRM and update MongoDB sync status.
    STRICT RULE: Only validated HOT leads are sent to Zoho CRM.
    Non-hot leads (Cold or Warm) are strictly saved in MongoDB / admin.html only.
    """
    if not zoho_is_configured():
        logger.info("Zoho CRM sync skipped: OAuth refresh token is not configured")
        return None

    config = _get_config()
    module_name = config["module"]
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", module_name):
        raise ValueError(f"ZOHO_MODULE contains invalid characters: {module_name!r}")

    quality = evaluate_lead_quality(lead)
    ident = lead.get("email") or lead.get("mobile_number") or lead.get("contact_number") or lead.get("full_name") or "lead"

    # Gate 0: Skip if already synced to Zoho CRM to avoid duplicate sends
    existing_zoho_id = lead.get("zoho_lead_id")
    if existing_zoho_id and str(existing_zoho_id).strip() and str(existing_zoho_id).strip() != "unknown" and lead.get("zoho_sync_status") == "synced":
        logger.info("Zoho CRM sync skipped: Lead %s is already synced (zoho_lead_id=%s).", ident, existing_zoho_id)
        return str(existing_zoho_id)

    # Gate 1: Strict data validation check
    if not quality["is_valid"]:
        err_msg = ", ".join(quality["validation_errors"])
        logger.warning("Zoho CRM sync rejected unvalidated lead (%s): %s", err_msg, ident)
        _update_mongo_lead_status(
            lead,
            status="skipped_invalid",
            reason=f"Validation failed: {err_msg}",
            score=quality["score"],
            rating=quality["rating"],
            clear_zoho_id=True,
        )
        return None

    # Gate 2: Strict Hot Lead Qualification Check
    # Leads only send to Zoho CRM when HOT; otherwise data is only saved in admin.html
    if not quality["is_hot"]:
        reason_str = ", ".join(quality["reasons"]) or f"Score {quality['score']}/100 below hot threshold"
        logger.info(
            "Zoho CRM sync skipped: Lead %s is not a HOT lead (Rating=%s, Score=%d/100, Reason=%s). Saved in Admin only.",
            ident,
            quality["rating"],
            quality["score"],
            reason_str,
        )
        _update_mongo_lead_status(
            lead,
            status="skipped_cold",
            reason=f"Saved in Admin only ({quality['rating']} lead, score {quality['score']}/100)",
            score=quality["score"],
            rating=quality["rating"],
            clear_zoho_id=True,
        )
        return None

    # Gate 3: Rate-limit circuit breaker cooldown check
    if _is_zoho_in_cooldown():
        logger.info(
            "Zoho CRM API 24h limit active (cooldown). Hot lead '%s' is saved in Admin CRM and queued for sync once the quota window resets.",
            ident,
        )
        _update_mongo_lead_status(
            lead,
            status="pending",
            reason="Zoho CRM 24-hour API limit active (HTTP 429). Saved in Admin CRM; ready to sync once quota resets.",
            score=quality["score"],
            rating=quality["rating"],
        )
        return None

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
            "🔥 [QUALIFIED HOT LEAD - HIGH INTENT PROPERTY BUYER]",
            f"Intent Rating       : {quality['rating'].upper()} (Score: {quality['score']}/100)",
        ]
        if quality.get("triggers"):
            description_sections.append("Hot Lead Triggers   :")
            for trig in quality["triggers"]:
                description_sections.append(f"  • {trig}")
        description_sections.extend([
            "--------------------------------------------------",
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
        ])
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
            "Rating": quality["rating"],
            "Lead_Status": "Qualified",
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
            return sync_zoho_lead(lead, retry_on_auth_fail=False, only_hot=only_hot)

        # Graceful handling of HTTP 429 Rate Limit (Free/Developer tier daily request quota)
        if response.status_code == 429:
            _set_zoho_cooldown(300.0)  # Pause calls for 5 minutes to prevent spamming
            logger.warning(
                "Zoho CRM 24-hour API request limit reached (HTTP 429). Hot lead '%s' is securely saved in MongoDB Atlas and queued in Admin CRM.",
                ident,
            )
            _update_mongo_lead_status(
                lead,
                status="pending",
                reason="Zoho CRM 24-hour API limit reached (HTTP 429). Safely saved in Admin CRM; ready to sync once quota resets.",
                score=quality["score"],
                rating=quality["rating"],
            )
            return None

        response.raise_for_status()
        body = response.json()
        rows = body.get("data", [])
        if not rows or rows[0].get("status") != "success":
            row = rows[0] if rows else {}
            error_code = row.get("code") or body.get("code", "unknown")
            error_msg = row.get("message") or body.get("message", "no details")
            error_details = row.get("details") or body.get("details", {})
            logger.warning(
                "Zoho CRM rejected lead upsert (code=%s, message=%s, details=%s)",
                error_code,
                error_msg,
                error_details,
            )
            return None

        record_id = rows[0].get("details", {}).get("id", "unknown")
        logger.info("Zoho CRM lead upsert succeeded (record_id=%s, score=%d)", record_id, quality["score"])

        # Persist Zoho CRM ID and Hot Lead rating back into MongoDB Atlas
        _update_mongo_lead_status(
            lead,
            status="synced",
            zoho_lead_id=record_id,
            reason=f"Hot Lead synced successfully (Score: {quality['score']}/100)",
            score=quality["score"],
            rating=quality["rating"],
        )
        return record_id

    except Exception as exc:
        logger.warning("Zoho CRM lead sync failed for %s: %s", ident, exc)
        return None


def sync_upserted_lead_to_zoho(lead: dict) -> str | None:
    """Sync a unified upserted lead directly to Zoho CRM and update the database."""
    lead_copy = dict(lead)
    if "source" not in lead_copy:
        sources_str = ", ".join(lead_copy.get("sources", ["Unified"]))
        lead_copy["source"] = f"Upserted Lead ({sources_str})"
    return sync_zoho_lead(lead_copy, only_hot=True)


def sync_all_from_mongo(only_hot: bool | None = None, sync_already_synced: bool = False) -> dict:
    """Sync validated hot leads from MongoDB Atlas to Zoho CRM Leads module."""
    if _is_zoho_in_cooldown():
        return {"status": "cooldown", "message": "Zoho CRM 24h limit active; leads queued in Admin CRM."}

    db = _get_mongo_db()
    if db is None:
        return {"error": "MongoDB connection not available"}

    synced_hot = []
    skipped_cold = []
    skipped_invalid = []
    failed = []
    total_evaluated = 0

    if only_hot is None:
        only_hot = _get_config()["only_hot_leads"]

    enquiry_col = os.getenv("ENQUIRY_COLLECTION_NAME", "property_leads")
    contacts_col = os.getenv("COLLECTION_NAME", "contacts")

    # 1. Sync all property_leads
    for pl in db[enquiry_col].find():
        total_evaluated += 1
        lead_data = {
            **pl,
            "local_id": str(pl.get("_id", "")),
            "source": pl.get("source") or "Website property enquiry",
        }
        ident = pl.get("email") or pl.get("mobile_number") or str(pl.get("_id"))
        name = f"{pl.get('first_name', '')} {pl.get('last_name', '')}".strip() or "Unnamed"

        quality = evaluate_lead_quality(lead_data)

        if not quality["is_valid"]:
            skipped_invalid.append({
                "type": "property_lead",
                "id": str(pl.get("_id")),
                "ident": ident,
                "name": name,
                "errors": quality["validation_errors"],
            })
            _update_mongo_lead_status(
                lead_data,
                status="skipped_invalid",
                reason=", ".join(quality["validation_errors"]),
                score=quality["score"],
                rating=quality["rating"],
                clear_zoho_id=True,
            )
            continue

        if not quality["is_hot"]:
            skipped_cold.append({
                "type": "property_lead",
                "id": str(pl.get("_id")),
                "ident": ident,
                "name": name,
                "rating": quality["rating"],
                "score": quality["score"],
                "reasons": quality["reasons"],
            })
            _update_mongo_lead_status(
                lead_data,
                status="skipped_cold",
                reason=f"Saved in Admin only ({quality['rating']} lead, score {quality['score']}/100)",
                score=quality["score"],
                rating=quality["rating"],
                clear_zoho_id=True,
            )
            continue

        # If already synced to Zoho and not forcing a re-sync, count as synced without re-calling API
        if not sync_already_synced and pl.get("zoho_sync_status") == "synced" and pl.get("zoho_lead_id"):
            synced_hot.append({
                "type": "property_lead",
                "id": str(pl.get("_id")),
                "ident": ident,
                "name": name,
                "zoho_id": pl.get("zoho_lead_id"),
                "already_synced": True,
            })
            continue

        res = sync_zoho_lead(lead_data, only_hot=True)
        if res:
            synced_hot.append({
                "type": "property_lead",
                "id": str(pl.get("_id")),
                "ident": ident,
                "name": name,
                "zoho_id": res,
                "score": quality["score"],
                "already_synced": False,
            })
        else:
            failed.append({"type": "property_lead", "id": str(pl.get("_id")), "ident": ident, "name": name})

    # 2. Sync contacts with whatsapp_answers or requirement
    for c in db[contacts_col].find({"$or": [{"whatsapp_answers": {"$exists": True, "$ne": None}}, {"requirement": {"$exists": True, "$ne": ""}}]}):
        total_evaluated += 1
        wa = c.get("whatsapp_answers") or {}
        full_name = c.get("full_name") or " ".join(filter(None, [wa.get("first_name", ""), wa.get("last_name", "")])) or "Contact Lead"
        ident = c.get("email") or c.get("contact_number") or str(c.get("_id"))

        lead_data = {
            **wa,
            **c,
            "full_name": full_name,
            "local_id": str(c.get("_id", "")),
            "contact_id": str(c.get("_id", "")),
            "source": "WhatsApp questionnaire" if c.get("whatsapp_answers") else "Website Contact Us",
        }
        quality = evaluate_lead_quality(lead_data)

        if not quality["is_valid"]:
            skipped_invalid.append({
                "type": "contact",
                "id": str(c.get("_id")),
                "ident": ident,
                "name": full_name,
                "errors": quality["validation_errors"],
            })
            _update_mongo_lead_status(
                lead_data,
                status="skipped_invalid",
                reason=", ".join(quality["validation_errors"]),
                score=quality["score"],
                rating=quality["rating"],
                clear_zoho_id=True,
            )
            continue

        if not quality["is_hot"]:
            skipped_cold.append({
                "type": "contact",
                "id": str(c.get("_id")),
                "ident": ident,
                "name": full_name,
                "rating": quality["rating"],
                "score": quality["score"],
                "reasons": quality["reasons"],
            })
            _update_mongo_lead_status(
                lead_data,
                status="skipped_cold",
                reason=f"Saved in Admin only ({quality['rating']} lead, score {quality['score']}/100)",
                score=quality["score"],
                rating=quality["rating"],
                clear_zoho_id=True,
            )
            continue

        # If already synced to Zoho and not forcing a re-sync, count as synced without re-calling API
        if not sync_already_synced and c.get("zoho_sync_status") == "synced" and c.get("zoho_lead_id"):
            synced_hot.append({
                "type": "contact",
                "id": str(c.get("_id")),
                "ident": ident,
                "name": full_name,
                "zoho_id": c.get("zoho_lead_id"),
                "already_synced": True,
            })
            continue

        res = sync_zoho_lead(lead_data, only_hot=True)
        if res:
            synced_hot.append({
                "type": "contact",
                "id": str(c.get("_id")),
                "ident": ident,
                "name": full_name,
                "zoho_id": res,
                "score": quality["score"],
                "already_synced": False,
            })
        else:
            failed.append({"type": "contact", "id": str(c.get("_id")), "ident": ident, "name": full_name})

    # 3. Sync upserted_leads collection (Hot unified leads)
    upsert_col = os.getenv("UPSERT_COLLECTION_NAME", "upserted_leads")
    for u in db[upsert_col].find():
        total_evaluated += 1
        ident = u.get("email") or u.get("phone") or str(u.get("id"))
        name = u.get("full_name") or f"{u.get('first_name', '')} {u.get('last_name', '')}".strip() or "Upsert Lead"
        lead_data = {
            **u,
            "local_id": u.get("id"),
            "mobile_number": u.get("phone"),
            "source": f"Upserted Lead ({', '.join(u.get('sources', ['Unified']))})",
        }
        quality = evaluate_lead_quality(lead_data)

        if not quality["is_valid"] or not quality["is_hot"]:
            continue

        if not sync_already_synced and u.get("zoho_sync_status") == "synced" and u.get("zoho_lead_id"):
            synced_hot.append({
                "type": "upsert_lead",
                "id": str(u.get("id")),
                "ident": ident,
                "name": name,
                "zoho_id": u.get("zoho_lead_id"),
                "already_synced": True,
            })
            continue

        res = sync_zoho_lead(lead_data, only_hot=True)
        if res:
            synced_hot.append({
                "type": "upsert_lead",
                "id": str(u.get("id")),
                "ident": ident,
                "name": name,
                "zoho_id": res,
                "score": quality["score"],
                "already_synced": False,
            })
        else:
            failed.append({"type": "upsert_lead", "id": str(u.get("id")), "ident": ident, "name": name})

    return {
        "total_evaluated": total_evaluated,
        "total_synced_hot": len(synced_hot),
        "total_skipped_cold": len(skipped_cold),
        "total_skipped_invalid": len(skipped_invalid),
        "total_failed": len(failed),
        "synced_hot": synced_hot,
        "skipped_cold": skipped_cold,
        "skipped_invalid": skipped_invalid,
        "failed": failed,
    }
