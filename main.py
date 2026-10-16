import asyncio
import html
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import smtplib
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from zoneinfo import ZoneInfoNotFoundError
from email.message import EmailMessage
from pathlib import Path
from urllib.parse import quote_plus, urlencode, urlsplit
import urllib.request

from bson import ObjectId
from bson.errors import InvalidId
from dotenv import load_dotenv
from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import AliasChoices, BaseModel, EmailStr, Field, field_validator
from pymongo import AsyncMongoClient
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError, PyMongoError
from starlette.concurrency import run_in_threadpool
from starlette.middleware.sessions import SessionMiddleware
from twilio.request_validator import RequestValidator
from location_service import is_verified_place, photon_locations, verified_locations

load_dotenv()
from zoho_crm import sync_zoho_lead

BASE_DIR = Path(__file__).resolve().parent
MONGODB_URI = os.getenv("MONGODB_URI")
DB_NAME = os.getenv("DB_NAME", "property_db")
COLLECTION_NAME = os.getenv("COLLECTION_NAME", "contacts")
ENQUIRY_COLLECTION_NAME = os.getenv("ENQUIRY_COLLECTION_NAME", "property_leads")

SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")
SENDER_NAME = os.getenv("SENDER_NAME", "Property Team")
AGENT_PHONE = os.getenv("AGENT_PHONE", "")
CALENDLY_URL = os.getenv("CALENDLY_URL", "https://calendly.com/shailendra-profilent/30min")
CALENDLY_WEBHOOK_SIGNING_KEY = os.getenv("CALENDLY_WEBHOOK_SIGNING_KEY", "")
CALENDLY_BOOKING_TEMPLATE_SID = os.getenv("TWILIO_WHATSAPP_BOOKING_TEMPLATE_SID", "")
CALENDLY_TOKEN = os.getenv("CALENDLY_TOKEN", "")

ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
_whatsapp_sender_setting = re.sub(
    r"^whatsapp:", "", os.getenv("TWILIO_WHATSAPP_FROM", "").strip(), flags=re.I
)
_whatsapp_sender_digits = re.sub(r"\D", "", _whatsapp_sender_setting)
TWILIO_WHATSAPP_FROM = (
    f"+{_whatsapp_sender_digits}"
    if _whatsapp_sender_setting.startswith("+")
    and 8 <= len(_whatsapp_sender_digits) <= 15
    and not _whatsapp_sender_digits.startswith("0")
    else ""
)
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")
WHATSAPP_BUSINESS_NUMBER = os.getenv("WHATSAPP_BUSINESS_NUMBER", "")
TWILIO_WHATSAPP_SANDBOX = re.sub(r"\D", "", TWILIO_WHATSAPP_FROM) == "14155238886"
IST = timezone(timedelta(hours=5, minutes=30))

logger = logging.getLogger("uvicorn.error")

SESSION_SECRET = os.getenv("SESSION_SECRET")
if not SESSION_SECRET:
    SESSION_SECRET = secrets.token_hex(32)
    logger.warning(
        "SESSION_SECRET is not set in .env - using a random one for this run. "
        "Admin logins will be forgotten every time the server restarts. "
        "Set SESSION_SECRET in .env to keep people logged in across restarts."
    )

from whatsapp_bot import (
    BOOKING_TEMPLATE_SID,
    LISTS,
    TEXT_PROMPTS,
    booking_window_open,
    dispatch_stage,
    find_list_stage,
    list_choice,
    menu_fallback,
    send_booking_confirmation,
    send_content,
    send_text,
    start_questionnaire,
    start_message_text,
    twiml,
    whatsapp_configuration,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not MONGODB_URI:
        raise RuntimeError("MONGODB_URI is missing. Add it to your .env file.")
    client = AsyncMongoClient(MONGODB_URI, tz_aware=True)
    app.state.client = client
    app.state.contacts = client[DB_NAME][COLLECTION_NAME]
    app.state.enquiries = client[DB_NAME][ENQUIRY_COLLECTION_NAME]
    app.state.whatsapp_conversations = client[DB_NAME]["whatsapp_conversations"]
    app.state.calendly_webhook_events = client[DB_NAME]["calendly_webhook_events"]
    await asyncio.gather(
        app.state.contacts.create_index([("created_at", -1)]),
        app.state.contacts.create_index("email"),
        app.state.contacts.create_index("contact_number"),
        app.state.enquiries.create_index([("created_at", -1)]),
        app.state.enquiries.create_index("email"),
        app.state.enquiries.create_index("mobile_number"),
        app.state.enquiries.create_index("whatsapp_number"),
        app.state.enquiries.create_index("whatsapp_conversation_id"),
        app.state.whatsapp_conversations.create_index("phone"),
        app.state.calendly_webhook_events.create_index("invitee_uri", unique=True),
    )
    yield
    await client.close()


app = FastAPI(title="Property Contact Form", lifespan=lifespan)
app.add_middleware(
    SessionMiddleware,
    secret_key=SESSION_SECRET,
    session_cookie="admin_session",
    max_age=60 * 60 * 8,
    same_site="lax",
)
class ContactForm(BaseModel):
    full_name: str = Field(min_length=2, max_length=100)
    email: EmailStr
    contact_number: str
    requirement: str = Field(default="", max_length=1000)
    whatsapp_opt_in: bool = False

    @field_validator("full_name")
    @classmethod
    def strip_text(cls, v: str) -> str:
        return v.strip()

    @field_validator("contact_number")
    @classmethod
    def valid_phone(cls, v: str) -> str:
        v = v.strip()
        if not re.fullmatch(r"\+?[0-9\s\-]{7,17}", v):
            raise ValueError("Enter a valid contact number")
        return v


def send_confirmation_email(name: str, to_email: str, property_address: str) -> None:
    """Send the buyer-inquiry reply. Runs in the background; failures are logged, not raised."""
    if not (SMTP_USER and SMTP_PASSWORD):
        logger.warning("SMTP_USER / SMTP_PASSWORD not set - confirmation email skipped.")
        return

    text_parts = [
        f"Dear {name},",
        f"Thank you for your interest in {property_address}. I would be happy to provide "
        "more details or schedule a private viewing at your convenience.",
    ]
    html_parts = [
        f"<p>Dear {html.escape(name)},</p>",
        f"<p>Thank you for your interest in <strong>{html.escape(property_address)}</strong>. "
        "I would be happy to provide more details or schedule a private viewing at your "
        "convenience.</p>",
    ]

    if CALENDLY_URL:
        text_parts.append(f"Book a meeting at a time that suits you:\n{CALENDLY_URL}")
        html_parts.append(
            "<p>Book a meeting at a time that suits you:</p>"
            f'<p><a href="{html.escape(CALENDLY_URL, quote=True)}" '
            'style="display:inline-block;background:#333333;color:#ffffff;padding:12px 24px;'
            'border-radius:6px;text-decoration:none;font-weight:600;">Schedule a Meeting</a></p>'
        )

    if AGENT_PHONE:
        tel = re.sub(r"[^\d+]", "", AGENT_PHONE)
        text_parts.append(f"Prefer to talk? Call our salesperson directly at {AGENT_PHONE}.")
        html_parts.append(
            "<p>Prefer to talk? Call our salesperson directly at "
            f'<a href="tel:{tel}"><strong>{html.escape(AGENT_PHONE)}</strong></a>.</p>'
        )

    text_parts.append(f"Warm regards,\n{SENDER_NAME}")
    html_parts.append(f"<p>Warm regards,<br>{html.escape(SENDER_NAME)}</p>")

    body = "\n\n".join(text_parts)
    body_html = "".join(html_parts)

    msg = EmailMessage()
    msg["Subject"] = "Thank you for your property enquiry"
    msg["From"] = f"{SENDER_NAME} <{SMTP_USER}>"
    msg["To"] = to_email
    msg.set_content(body)
    msg.add_alternative(body_html, subtype="html")

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=20) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.send_message(msg)
    except Exception:
        logger.exception("Could not send confirmation email to %s", to_email)


@app.post("/api/contact", status_code=201)
async def create_contact(form: ContactForm, background_tasks: BackgroundTasks):
    doc = form.model_dump()
    if not doc.get("requirement"):
        doc.pop("requirement", None)

    whatsapp_phone = re.sub(r"[\s()-]", "", form.contact_number)
    if not re.fullmatch(r"\+[1-9][0-9]{7,14}", whatsapp_phone):
        raise HTTPException(
            status_code=422,
            detail="Enter the WhatsApp number in international format, e.g. +919876543210.",
        )

    doc["contact_number"] = whatsapp_phone
    doc["created_at"] = datetime.now(timezone.utc)
    if form.whatsapp_opt_in:
        doc["whatsapp_opt_in_source"] = "contact_form_checkbox"
        doc["whatsapp_opt_in_at"] = datetime.now(timezone.utc)

    try:
        result = await app.state.contacts.insert_one(doc)
    except PyMongoError:
        raise HTTPException(
            status_code=500,
            detail="Could not save your details. Please try again.",
        )

    background_tasks.add_task(
        sync_zoho_lead,
        {
            **doc,
            "source": "Website contact form",
            "local_id": str(result.inserted_id),
        },
    )
    background_tasks.add_task(
        send_confirmation_email,
        form.full_name,
        str(form.email),
        "our properties",
    )

    whatsapp_result = {"started": False, "status": "not_requested", "missing": []}
    if form.whatsapp_opt_in:
        whatsapp_result = await start_questionnaire(
            app.state.whatsapp_conversations,
            phone=whatsapp_phone,
            contact_id=str(result.inserted_id),
            background_tasks=background_tasks,
            full_name=form.full_name,
            email=str(form.email),
        )

    return {
        "message": "Your enquiry was saved.",
        "email_status": "queued",
        "whatsapp_started": whatsapp_result["started"],
        "whatsapp_status": whatsapp_result["status"],
        "whatsapp_missing_settings": whatsapp_result.get("missing", []),
        "id": str(result.inserted_id),
    }

CHOICES = {
    "planning_to_buy": [
        "Immediately",
        "Within 1 Month",
        "Within 3 Months",
        "Within 6 Months",
        "Within 12 Months",
        "More Than 1 Year",
        "Just Exploring / Researching",
    ],
    "budget_range": [
        "Up to 25 lakh",
        "25 lakh - 50 lakh",
        "50 lakh - 1 crore",
        "1 crore - 2 crore",
        "Above 2 crore",
    ],
    "payment_option": [
        "Bank Finance with EMI",
        "Full Cash Payment",
        "Home Loan (Mortgage)",
        "Down Payment Plan",
        "Construction-Linked Payment Plan (CLP)",
        "Possession-Linked Payment Plan (PLP)",
        "Installment Payment Plan",
        "Developer Financing",
        "Rent-to-Own Scheme",
        "Part Cash + Home Loan",
        "Part Payment with Balance at Registration",
        "Flexible Payment Plan",
        "Subvention Scheme (Developer Pays Pre-EMI)",
        "Joint Home Loan (Co-applicant Financing)",
        "NRI Payment Plan (for Overseas Buyers)",
    ],
    "bhk_preference": [
        "1 RK",
        "1 BHK",
        "2 BHK",
        "2.5 BHK",
        "3 BHK",
        "3.5 BHK",
        "4 BHK",
        "5 BHK+",
        "Villa",
        "Penthouse",
    ],
}

class EnquiryForm(BaseModel):
    first_name: str = Field(min_length=2, max_length=50)
    last_name: str = Field(default="", max_length=50)
    email: EmailStr
    mobile_number: str
    location_preference: str = Field(min_length=2, max_length=150)
    planning_to_buy: str
    budget_range: str
    payment_option: str
    bhk_preference: str
    remarks_requirements: str = Field(
        default="",
        max_length=1000,
        validation_alias=AliasChoices("remarks_requirements", "remarks"),
    )

    @field_validator("first_name", "last_name", "location_preference", "remarks_requirements")
    @classmethod
    def strip_text(cls, v: str) -> str:
        return v.strip()

    @field_validator("mobile_number")
    @classmethod
    def valid_mobile(cls, v: str) -> str:
        cleaned = re.sub(r"[\s-]", "", v)
        if not re.fullmatch(r"\+?[0-9]{10,15}", cleaned):
            raise ValueError("Enter a valid mobile number")
        return cleaned

    @field_validator("planning_to_buy", "budget_range", "payment_option", "bhk_preference")
    @classmethod
    def valid_choice(cls, v: str, info) -> str:
        if v not in CHOICES[info.field_name]:
            raise ValueError("Select a valid option")
        return v


@app.get("/api/locations")
async def search_locations(q: str = Query(min_length=3, max_length=100)):
    try:
        return {"locations": await run_in_threadpool(photon_locations, q.strip())}
    except Exception:
        logger.exception("Location search provider failed")
        raise HTTPException(status_code=503, detail="Location verification is temporarily unavailable.")


@app.post("/api/enquiry", status_code=201)
async def create_enquiry(form: EnquiryForm, background_tasks: BackgroundTasks):
    try:
        matches = await run_in_threadpool(verified_locations, form.location_preference)
    except Exception:
        logger.exception("Location verification provider failed")
        raise HTTPException(status_code=503, detail="We could not verify this location right now. Please try again shortly.")
    if form.location_preference.casefold() not in {item.casefold() for item in matches}:
        raise HTTPException(status_code=422, detail="Choose a location from the verified suggestions.")
    doc = form.model_dump()
    doc["created_at"] = datetime.now(timezone.utc)
    try:
        result = await app.state.enquiries.insert_one(doc)
    except PyMongoError:
        raise HTTPException(status_code=500, detail="Could not save your enquiry. Please try again.")
    full_name = f"{form.first_name} {form.last_name}".strip()
    background_tasks.add_task(
        sync_zoho_lead,
        {
            **doc,
            "full_name": full_name,
            "source": "Website property enquiry",
            "local_id": str(result.inserted_id),
        },
    )
    background_tasks.add_task(
        send_confirmation_email, full_name, form.email, f"properties in {form.location_preference}"
    )
    return {"message": "Thank you! Your enquiry has been submitted. We will contact you shortly.", "id": str(result.inserted_id)}


# ---------------------------------------------------------------- Admin auth
class AdminLogin(BaseModel):
    username: str
    password: str


def require_admin(request: Request) -> None:
    if not ADMIN_PASSWORD:
        raise HTTPException(status_code=503, detail="Set ADMIN_PASSWORD in your .env file to use the admin panel.")
    if not request.session.get("admin"):
        raise HTTPException(status_code=401, detail="Not logged in")


@app.get("/admin/login", include_in_schema=False)
async def admin_login_page():
    return FileResponse(BASE_DIR / "admin" / "login.html")


@app.post("/admin/login")
async def admin_login(data: AdminLogin, request: Request):
    if not ADMIN_PASSWORD:
        raise HTTPException(status_code=503, detail="Set ADMIN_PASSWORD in your .env file to use the admin panel.")
    user_ok = secrets.compare_digest(data.username.strip().encode(), ADMIN_USERNAME.encode())
    pass_ok = secrets.compare_digest(data.password.encode(), ADMIN_PASSWORD.encode())
    if not (user_ok and pass_ok):
        raise HTTPException(status_code=401, detail="Invalid username or password")
    request.session["admin"] = True
    return {"message": "ok"}


@app.post("/admin/logout")
async def admin_logout(request: Request):
    request.session.clear()
    return {"message": "ok"}


@app.get("/admin", include_in_schema=False)
async def admin_page(request: Request):
    if not request.session.get("admin"):
        return RedirectResponse("/admin/login")
    return FileResponse(BASE_DIR / "admin" / "admin.html")


# ------------------------------------------------------------- Admin: leads
def oid(lead_id: str) -> ObjectId:
    try:
        return ObjectId(lead_id)
    except (InvalidId, TypeError):
        raise HTTPException(status_code=400, detail="Invalid lead id")


async def latest_docs(collection, limit: int = 500):
    docs = await collection.find().sort("created_at", -1).limit(limit).to_list()
    for d in docs:
        d["id"] = str(d.pop("_id"))
        d["created_at"] = d["created_at"].isoformat()
    return docs


@app.get("/api/admin/summary", dependencies=[Depends(require_admin)])
async def admin_summary():
    start = datetime.now(IST).replace(hour=0, minute=0, second=0, microsecond=0)
    today = {"created_at": {"$gte": start}}
    contacts, enquiries = app.state.contacts, app.state.enquiries
    (
        contacts_total,
        enquiries_total,
        contacts_today,
        enquiries_today,
        immediate,
        cash,
        high_budget,
        bhk_cursor,
    ) = await asyncio.gather(
        contacts.count_documents({}),
        enquiries.count_documents({}),
        contacts.count_documents(today),
        enquiries.count_documents(today),
        enquiries.count_documents({"planning_to_buy": {"$in": ["Immediately", "Within 1 Month"]}}),
        enquiries.count_documents({"payment_option": "Full Cash Payment"}),
        enquiries.count_documents({"budget_range": {"$in": ["1 crore - 2 crore", "Above 2 crore"]}}),
        enquiries.aggregate([
            {"$group": {"_id": "$bhk_preference", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}},
        ]),
    )
    bhk = {d["_id"]: d["count"] for d in await bhk_cursor.to_list()}
    return {
        "total": contacts_total + enquiries_total,
        "cards": {
            "new_today": contacts_today + enquiries_today,
            "contacts_total": contacts_total,
            "enquiries_total": enquiries_total,
            "immediate": immediate,
            "cash": cash,
            "high_budget": high_budget,
        },
        "bhk": bhk,
        "whatsapp": whatsapp_configuration(),
    }


# Contact Us leads - full CRUD
@app.get("/api/admin/contacts", dependencies=[Depends(require_admin)])
async def admin_list_contacts():
    return await latest_docs(app.state.contacts)


@app.post("/api/admin/contacts", status_code=201, dependencies=[Depends(require_admin)])
async def admin_create_contact(form: ContactForm):
    doc = form.model_dump()
    doc["created_at"] = datetime.now(timezone.utc)
    result = await app.state.contacts.insert_one(doc)
    return {"id": str(result.inserted_id)}


@app.put("/api/admin/contacts/{lead_id}", dependencies=[Depends(require_admin)])
async def admin_update_contact(lead_id: str, form: ContactForm):
    result = await app.state.contacts.update_one({"_id": oid(lead_id)}, {"$set": form.model_dump()})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Lead not found")
    return {"message": "Lead updated"}


@app.delete("/api/admin/contacts/{lead_id}", dependencies=[Depends(require_admin)])
async def admin_delete_contact(lead_id: str):
    result = await app.state.contacts.delete_one({"_id": oid(lead_id)})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Lead not found")
    return {"message": "Lead deleted"}


# Property Enquiries - full CRUD
@app.get("/api/admin/enquiries", dependencies=[Depends(require_admin)])
async def admin_list_enquiries():
    return await latest_docs(app.state.enquiries)


@app.post("/api/admin/enquiries", status_code=201, dependencies=[Depends(require_admin)])
async def admin_create_enquiry(form: EnquiryForm):
    doc = form.model_dump()
    doc["created_at"] = datetime.now(timezone.utc)
    result = await app.state.enquiries.insert_one(doc)
    return {"id": str(result.inserted_id)}


@app.put("/api/admin/enquiries/{lead_id}", dependencies=[Depends(require_admin)])
async def admin_update_enquiry(lead_id: str, form: EnquiryForm):
    result = await app.state.enquiries.update_one({"_id": oid(lead_id)}, {"$set": form.model_dump()})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Lead not found")
    return {"message": "Lead updated"}


@app.delete("/api/admin/enquiries/{lead_id}", dependencies=[Depends(require_admin)])
async def admin_delete_enquiry(lead_id: str):
    result = await app.state.enquiries.delete_one({"_id": oid(lead_id)})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Lead not found")
    return {"message": "Lead deleted"}


app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")


@app.get("/", include_in_schema=False)
async def home():
    return FileResponse(BASE_DIR / "static" / "index.html")


@app.get("/enquiry", include_in_schema=False)
async def enquiry_page():
    return FileResponse(BASE_DIR / "static" / "enquiry.html")


@app.get("/whatsapp", include_in_schema=False)
async def start_whatsapp_chat():
    # The visitor starts the chat, which also supports Twilio Sandbox testing.
    target = WHATSAPP_BUSINESS_NUMBER or (TWILIO_WHATSAPP_FROM if TWILIO_WHATSAPP_SANDBOX else "")
    number = re.sub(r"\D", "", target)
    if not number:
        raise HTTPException(status_code=503, detail="WhatsApp chat is not configured")
    return RedirectResponse(
        f"https://wa.me/{number}?text=Hi",
        status_code=307,
    )


@app.get("/schedule", include_in_schema=False)
async def schedule_page():
    return FileResponse(BASE_DIR / "static" / "schedule.html")


@app.get("/booking/redirect", include_in_schema=False)
async def booking_redirect(
    event_uri: str = "",
    invitee_uri: str = "",
    event_start_time: str = "",
    event_type_name: str = "",
    invitee_full_name: str = "",
    to: str = "agent",
):
    """Redirect invitee after Calendly booking to WhatsApp with meeting date/time pre-filled."""
    if to == "bot":
        target = WHATSAPP_BUSINESS_NUMBER or (TWILIO_WHATSAPP_FROM if TWILIO_WHATSAPP_SANDBOX else "")
    else:
        target = AGENT_PHONE or WHATSAPP_BUSINESS_NUMBER or (TWILIO_WHATSAPP_FROM if TWILIO_WHATSAPP_SANDBOX else "")

    number = re.sub(r"\D", "", target)
    if not number:
        raise HTTPException(status_code=503, detail="WhatsApp target number is not configured")

    event_resource = None
    invitee_resource = None
    if CALENDLY_TOKEN:
        if event_uri and not is_calendly_resource_uri(event_uri, "event"):
            raise HTTPException(status_code=422, detail="Invalid Calendly event reference")
        if invitee_uri and not is_calendly_resource_uri(invitee_uri, "invitee"):
            raise HTTPException(status_code=422, detail="Invalid Calendly invitee reference")

        event_request = (
            run_in_threadpool(fetch_calendly_resource, event_uri)
            if event_uri else asyncio.sleep(0, result=None)
        )
        invitee_request = (
            run_in_threadpool(fetch_calendly_resource, invitee_uri)
            if invitee_uri and not invitee_full_name else asyncio.sleep(0, result=None)
        )
        event_resource, invitee_resource = await asyncio.gather(
            event_request, invitee_request, return_exceptions=True
        )
        if isinstance(event_resource, Exception):
            logger.warning("Could not retrieve Calendly event details: %s", event_resource)
            event_resource = None
        if isinstance(invitee_resource, Exception):
            logger.warning("Could not retrieve Calendly invitee details: %s", invitee_resource)
            invitee_resource = None

    if event_resource:
        event_start_time = event_resource.get("start_time") or event_start_time
        event_type_name = event_resource.get("name") or event_type_name
    if invitee_resource:
        invitee_full_name = invitee_resource.get("name") or invitee_full_name

    formatted_time = ""
    if event_start_time:
        try:
            instant = datetime.fromisoformat(event_start_time.replace("Z", "+00:00"))
            formatted_time = instant.astimezone(IST).strftime("%A, %d %B %Y at %I:%M %p (IST)")
        except Exception:
            formatted_time = event_start_time

    meeting_name = event_type_name or "Property Meeting"
    name_str = f"Hi, I'm {invitee_full_name.strip()}." if invitee_full_name.strip() else "Hi!"

    if formatted_time:
        text = f"{name_str} I have scheduled a meeting ({meeting_name}) for {formatted_time}."
    else:
        text = f"{name_str} I have scheduled a meeting ({meeting_name})."

    return RedirectResponse(
        f"https://wa.me/{number}?text={quote_plus(text)}",
        status_code=302,
    )

@app.post("/webhooks/whatsapp")
async def whatsapp_webhook(request: Request, background_tasks: BackgroundTasks):
    form = await request.form()
    params = dict(form)
    if not TWILIO_AUTH_TOKEN or not PUBLIC_BASE_URL:
        raise HTTPException(status_code=503, detail="Twilio webhook is not configured")

    signature = request.headers.get("X-Twilio-Signature", "")
    webhook_url = f"{PUBLIC_BASE_URL}/webhooks/whatsapp"

    try:
        valid = RequestValidator(TWILIO_AUTH_TOKEN).validate(
            webhook_url,
            params,
            signature,
        )
        if not valid:
            raise HTTPException(status_code=403, detail="Invalid Twilio signature")
    except HTTPException:
        raise
    except Exception:
        logger.exception("Twilio webhook validation failed")
        raise HTTPException(status_code=403, detail="Invalid Twilio signature")

    sender = str(form.get("From", ""))
    if not sender.startswith("whatsapp:"):
        raise HTTPException(status_code=400, detail="Expected a WhatsApp message")
    phone = sender.removeprefix("whatsapp:")
    text = str(form.get("Body", "")).strip()
    conversations = request.app.state.whatsapp_conversations
    now = datetime.now(timezone.utc)
    conversation = await conversations.find_one({"phone": phone})
    if not conversation:
        # This also lets the existing wa.me link start a customer-initiated chat.
        await conversations.insert_one({
            "phone": phone,
            "stage": "q1_first_name",
            "answers": {},
            "status": "in_progress",
            "created_at": now,
            "updated_at": now,
            "last_inbound_at": now,
        })
        return twiml(TEXT_PROMPTS["q1_first_name"])
    await conversations.update_one({"phone": phone}, {"$set": {"last_inbound_at": now}})

    if text.upper() == "STOP":
        await conversations.update_one(
            {"phone": phone},
            {"$set": {"status": "stopped", "updated_at": datetime.now(timezone.utc)}},
        )
        return twiml("You have been opted out of this WhatsApp conversation.")
    if text.upper() in {"START", "RESTART", "RESET"}:
        await conversations.update_one(
            {"phone": phone},
            {"$set": {
                "stage": "q1_first_name",
                "answers": {},
                "status": "in_progress",
                "updated_at": datetime.now(timezone.utc),
            }},
        )
        return twiml(TEXT_PROMPTS["q1_first_name"])

    if conversation.get("status") == "complete":
        calendly_link = os.getenv("CALENDLY_URL", CALENDLY_URL)
        return twiml(
            "Your answers have already been recorded. Our team will contact you shortly."
            f"\n\nChoose a convenient date and time to meet here: {calendly_link}"
        )
    if conversation.get("status") == "awaiting_customer_start":
        await conversations.update_one(
            {"phone": phone},
            {"$set": {"status": "awaiting_location", "updated_at": datetime.now(timezone.utc)}},
        )
        answers = conversation.get("answers", {})
        full_name = " ".join(
            part for part in (answers.get("first_name", ""), answers.get("last_name", "")) if part
        )
        return twiml(start_message_text(
            full_name,
            answers.get("email", ""),
            answers.get("mobile_number", phone),
        ))

    stage = conversation.get("stage", "q1_first_name")
    answers = conversation.get("answers", {})

    if stage == "q5_location_checking":
        return twiml("I'm still checking that location. I'll send the next question as soon as it's verified.")

    list_stage = find_list_stage(stage)
    if list_stage:
        selected = list_choice(list_stage, form)
        if selected is None:
            return twiml(menu_fallback(list_stage))
        _, stored_value = selected
        if stage == "q8_category":
            category_stages = {
                "Loan / Bank Finance": "q8_loan",
                "Cash / Down Payment": "q8_cash",
                "Developer Plans": "q8_developer",
            }
            if stored_value == "NRI Payment Plan (for Overseas Buyers)":
                answers["payment_option"] = stored_value
                next_stage = "q9_bhk"
            else:
                next_stage = category_stages[stored_value]
        elif stage == "q6_planning":
            answers["planning_to_buy"] = stored_value
            next_stage = "q7_budget"
        elif stage == "q7_budget":
            answers["budget_range"] = stored_value
            next_stage = "q8_category"
        elif stage == "q9_bhk":
            answers["bhk_preference"] = stored_value
            next_stage = "q10_remarks"
        else:
            answers["payment_option"] = stored_value
            next_stage = "q9_bhk"
        await conversations.update_one(
            {"phone": phone},
            {"$set": {"answers": answers, "stage": next_stage, "updated_at": datetime.now(timezone.utc)}},
        )
        return twiml(dispatch_stage(next_stage, phone, answers, background_tasks))

    if stage == "q1_first_name":
        candidate = text.strip()
        if len(candidate) < 2 or not candidate.isalpha():
            return twiml("Please enter your first name using letters only (at least 2 letters).\n\n" + TEXT_PROMPTS[stage])
        answers["first_name"] = candidate
        next_stage = "q2_last_name"
    elif stage == "q2_last_name":
        answers["last_name"] = "" if text.casefold() == "skip" else text[:100]
        next_stage = "q3_email"
    elif stage == "q3_email":
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", text):
            return twiml(TEXT_PROMPTS["q3_email_invalid"])
        answers["email"] = text
        next_stage = "q4_mobile"
    elif stage == "q4_mobile":
        button_payload = str(form.get("ButtonPayload", "")).strip()
        button_text = str(form.get("ButtonText", "")).strip()
        response = (button_payload or button_text or text).casefold()
        if response in {"mobile_same", "yes, same number", "yes", "same number"}:
            answers["mobile_number"] = phone
            next_stage = "q5_location"
        elif response in {"mobile_other", "use another number"}:
            next_stage = "q4_mobile_other"
        else:
            digits = re.sub(r"\D", "", text)
            if len(digits) == 10:
                answers["mobile_number"] = digits
                next_stage = "q5_location"
            else:
                fallback = f"Is *{phone}* the best number to reach you? Reply *Yes*, or type another 10-digit number."
                return twiml(fallback)
    elif stage == "q4_mobile_other":
        digits = re.sub(r"\D", "", text)
        if len(digits) != 10:
            return twiml(TEXT_PROMPTS[stage])
        answers["mobile_number"] = digits
        next_stage = "q5_location"
    elif stage == "q5_location":
        if len(text.strip()) < 3:
            return twiml("That doesn't look like a city or area name. Please enter the location again.\n\n" + TEXT_PROMPTS[stage])
        claim = await conversations.update_one(
            {"_id": conversation["_id"], "stage": "q5_location"},
            {"$set": {
                "stage": "q5_location_checking",
                "pending_location": text[:150],
                "updated_at": now,
            }},
        )
        if not claim.modified_count:
            return twiml("I'm already checking your location. I'll send the next question shortly.")
        background_tasks.add_task(
            verify_whatsapp_location_and_continue,
            conversations,
            phone,
            conversation["_id"],
            text[:150],
        )
        return twiml("Thanks. I'm checking that location now and will send the next question shortly.")
    elif stage == "q10_remarks":
        answers["remarks_requirements"] = "" if text.casefold() == "skip" else text[:1000]
        conversation_id = str(conversation["_id"])
        lead = {
            "first_name": answers.get("first_name", ""),
            "last_name": answers.get("last_name", ""),
            "email": answers.get("email", ""),
            "mobile_number": answers.get("mobile_number", phone),
            "location_preference": answers.get("location_preference", ""),
            "planning_to_buy": answers.get("planning_to_buy", ""),
            "budget_range": answers.get("budget_range", ""),
            "payment_option": answers.get("payment_option", ""),
            "bhk_preference": answers.get("bhk_preference", ""),
            "remarks_requirements": answers.get("remarks_requirements", answers.get("remarks", "")),
            "whatsapp_number": phone,
            "whatsapp_conversation_id": conversation_id,
            "source": "contact_us_whatsapp",
            "created_at": conversation.get("created_at", datetime.now(timezone.utc)),
            "completed_at": datetime.now(timezone.utc),
        }
        try:
            lead_result = await request.app.state.enquiries.update_one(
                {"whatsapp_conversation_id": conversation_id},
                {"$set": lead},
                upsert=True,
            )
        except Exception:
            logger.exception("Could not save WhatsApp questionnaire to property_leads")
            return twiml("Sorry, I couldn't save your answers just now. Please send your remarks again.")

        background_tasks.add_task(
            sync_zoho_lead,
            {
                **lead,
                "full_name": " ".join(
                    part for part in (lead["first_name"], lead["last_name"]) if part
                ),
                "source": "WhatsApp property questionnaire",
                "local_id": str(lead_result.upserted_id or conversation_id),
            },
        )
        contact_id = conversation.get("contact_id")
        if contact_id:
            try:
                await request.app.state.contacts.update_one(
                    {"_id": ObjectId(contact_id)},
                    {"$set": {"whatsapp_answers": answers, "whatsapp_flow_status": "complete"}},
                )
            except Exception:
                logger.exception("Could not attach WhatsApp answers to contact %s", contact_id)
        await conversations.update_one(
            {"phone": phone},
            {"$set": {
                "answers": answers,
                "status": "complete",
                "stage": "complete",
                "property_lead_id": str(lead_result.upserted_id) if lead_result.upserted_id else None,
                "updated_at": datetime.now(timezone.utc),
            }},
        )
        first_name = answers.get("first_name", "there")
        calendly_link = os.getenv("CALENDLY_URL", CALENDLY_URL)
        return twiml(
            f"✅ Thank you, {first_name}! Our team will contact you shortly with matching options."
            f"\n\nChoose a convenient date and time to meet here: {calendly_link}"
        )
    else:
        return twiml("Sorry, I couldn't match that answer. Please reply START to restart.")

    await conversations.update_one(
        {"phone": phone},
        {"$set": {"answers": answers, "stage": next_stage, "status": "in_progress", "updated_at": datetime.now(timezone.utc)}},
    )
    return twiml(dispatch_stage(next_stage, phone, answers, background_tasks))


async def verify_whatsapp_location_and_continue(conversations, phone: str, conversation_id, query: str):
    """Validate a WhatsApp location after the webhook has already acknowledged the message."""
    try:
        locations = await run_in_threadpool(verified_locations, query)
    except Exception:
        logger.exception("WhatsApp location validation failed for conversation %s", conversation_id)
        reply = "I couldn't verify that location right now. Please try another spelling.\n\n" + TEXT_PROMPTS["q5_location"]
        result = await conversations.update_one(
            {"_id": conversation_id, "stage": "q5_location_checking", "pending_location": query},
            {"$set": {"stage": "q5_location", "updated_at": datetime.now(timezone.utc)}, "$unset": {"pending_location": ""}},
        )
        if result.modified_count:
            await run_in_threadpool(send_text, phone, reply)
        return

    if not is_verified_place(query, locations):
        reply = "I couldn't verify that city or area. Please check the spelling and try again.\n\n" + TEXT_PROMPTS["q5_location"]
        result = await conversations.update_one(
            {"_id": conversation_id, "stage": "q5_location_checking", "pending_location": query},
            {"$set": {"stage": "q5_location", "updated_at": datetime.now(timezone.utc)}, "$unset": {"pending_location": ""}},
        )
        if result.modified_count:
            await run_in_threadpool(send_text, phone, reply)
        return

    normalized_query = " ".join(query.casefold().split())
    canonical_location = next(
        label for label in locations
        if any(" ".join(part.casefold().split()) == normalized_query for part in label.split(","))
    )
    current = await conversations.find_one({"_id": conversation_id, "stage": "q5_location_checking", "pending_location": query})
    if not current:
        return
    answers = current.get("answers", {})
    answers["location_preference"] = canonical_location
    result = await conversations.update_one(
        {"_id": conversation_id, "stage": "q5_location_checking", "pending_location": query},
        {"$set": {
            "answers": answers,
            "stage": "q6_planning",
            "updated_at": datetime.now(timezone.utc),
        }, "$unset": {"pending_location": ""}},
    )
    if not result.modified_count:
        return

    planning_menu_sid = LISTS["q6_planning"]["sid"]
    message_sid = None
    if planning_menu_sid:
        try:
            message_sid = await run_in_threadpool(send_content, phone, planning_menu_sid)
        except Exception:
            logger.exception("Could not send WhatsApp planning list to %s; using text fallback", phone)
    if not message_sid:
        try:
            await run_in_threadpool(send_text, phone, menu_fallback("q6_planning"))
        except Exception:
            logger.exception("Could not send WhatsApp planning fallback to %s", phone)


@app.post("/webhooks/calendly", include_in_schema=False)
async def calendly_webhook(request: Request, background_tasks: BackgroundTasks):
    """Send an approved WhatsApp booking template after a Calendly invitee books."""
    if not CALENDLY_WEBHOOK_SIGNING_KEY:
        raise HTTPException(status_code=503, detail="Calendly webhook signing key is not configured")
    raw_body = await request.body()
    signature_header = request.headers.get("Calendly-Webhook-Signature", "")
    signature_parts = dict(
        part.split("=", 1) for part in signature_header.split(",") if "=" in part
    )
    timestamp = signature_parts.get("t", "")
    supplied_signature = signature_parts.get("v1", "")
    try:
        timestamp_int = int(timestamp)
    except ValueError:
        raise HTTPException(status_code=403, detail="Invalid Calendly signature")
    if abs(datetime.now(timezone.utc).timestamp() - timestamp_int) > 180:
        raise HTTPException(status_code=403, detail="Expired Calendly webhook")
    signed_payload = timestamp.encode() + b"." + raw_body
    expected_signature = hmac.new(
        CALENDLY_WEBHOOK_SIGNING_KEY.encode(), signed_payload, hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(expected_signature, supplied_signature):
        raise HTTPException(status_code=403, detail="Invalid Calendly signature")

    try:
        envelope = json.loads(raw_body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise HTTPException(status_code=400, detail="Invalid JSON payload")
    if not isinstance(envelope, dict) or not isinstance(envelope.get("payload") or {}, dict):
        raise HTTPException(status_code=400, detail="Invalid Calendly event payload")
    if envelope.get("event") != "invitee.created":
        return {"received": True, "ignored": True}
    payload = envelope.get("payload") or {}
    return await process_calendly_invitee(payload, request.app.state, background_tasks)


class CalendlyBookingFallback(BaseModel):
    event_uri: str = Field(min_length=1, max_length=500)
    invitee_uri: str = Field(min_length=1, max_length=500)


def fetch_calendly_resource(uri: str) -> dict:
    request = urllib.request.Request(
        uri,
        headers={"Authorization": f"Bearer {CALENDLY_TOKEN}", "User-Agent": "ProfilentApp/1.0"},
    )
    with urllib.request.urlopen(request, timeout=8) as response:
        result = json.loads(response.read().decode("utf-8"))
    resource = result.get("resource")
    if not isinstance(resource, dict):
        raise ValueError("Calendly response has no resource")
    return resource


def is_calendly_resource_uri(uri: str, resource_type: str) -> bool:
    parsed = urlsplit(uri)
    if parsed.scheme != "https" or parsed.hostname != "api.calendly.com" or parsed.query or parsed.fragment:
        return False
    parts = [part for part in parsed.path.split("/") if part]
    if parts[:2] == ["api", "v2"]:
        parts = parts[2:]
    if resource_type == "event":
        return len(parts) == 2 and parts[0] == "scheduled_events"
    return len(parts) == 4 and parts[0] == "scheduled_events" and parts[2] == "invitees"


@app.post("/api/calendly/booking-confirmation", include_in_schema=False)
async def calendly_booking_confirmation_fallback(
    form: CalendlyBookingFallback,
    request: Request,
    background_tasks: BackgroundTasks,
):
    """Fallback for the Calendly widget when its server webhook is delayed or unavailable."""
    if not CALENDLY_TOKEN:
        raise HTTPException(status_code=503, detail="Calendly API fallback is not configured")
    if not is_calendly_resource_uri(form.event_uri, "event") or not is_calendly_resource_uri(form.invitee_uri, "invitee"):
        raise HTTPException(status_code=422, detail="Invalid Calendly event reference")
    try:
        event, invitee = await asyncio.gather(
            run_in_threadpool(fetch_calendly_resource, form.event_uri),
            run_in_threadpool(fetch_calendly_resource, form.invitee_uri),
        )
    except Exception as exc:
        logger.exception("Could not retrieve scheduled booking from Calendly API")
        raise HTTPException(status_code=502, detail="Could not retrieve your Calendly booking. Please contact our team.") from exc
    referenced_event = str(invitee.get("event", ""))
    retrieved_event = str(event.get("uri", ""))
    if (referenced_event and referenced_event != form.event_uri) or (retrieved_event and retrieved_event != form.event_uri):
        raise HTTPException(status_code=422, detail="The Calendly invitee does not belong to this event")
    if invitee.get("status") != "active":
        return {"received": True, "ignored": True, "reason": "invitee is not active"}

    name = str(invitee.get("name") or "").strip()
    if not name:
        name = " ".join(filter(None, [invitee.get("first_name"), invitee.get("last_name")]))
    payload = {
        "scheduled_event": event,
        "event": event.get("uri", form.event_uri),
        "uri": invitee.get("uri", form.invitee_uri),
        "name": name,
        "email": invitee.get("email", ""),
        "timezone": invitee.get("timezone", "UTC"),
        "text_reminder_number": invitee.get("text_reminder_number", ""),
        "questions_and_answers": invitee.get("questions_and_answers", []),
        "reschedule_url": invitee.get("reschedule_url", ""),
        "cancel_url": invitee.get("cancel_url", ""),
    }
    return await process_calendly_invitee(payload, request.app.state, background_tasks)


async def process_calendly_invitee(payload: dict, state, background_tasks: BackgroundTasks):
    scheduled_event = payload.get("scheduled_event") or {}
    email = str(payload.get("email", "")).strip()
    invitee_uri = str(payload.get("uri", "")).strip()
    booking_phone = normalize_e164(payload.get("text_reminder_number", ""))
    answers = payload.get("questions_and_answers") or []
    if not booking_phone:
        for answer in answers:
            if isinstance(answer, dict) and re.search(r"phone|mobile|whatsapp|telephone", str(answer.get("question", "")), re.I):
                booking_phone = normalize_e164(answer.get("answer", ""))
                if booking_phone:
                    break
    if not invitee_uri:
        return {"received": True, "ignored": True, "reason": "missing invitee identity"}
    events = state.calendly_webhook_events
    now = datetime.now(timezone.utc)
    try:
        await events.insert_one({"invitee_uri": invitee_uri, "email": email, "phone": booking_phone, "status": "processing", "received_at": now, "lease_until": now + timedelta(minutes=5)})
    except DuplicateKeyError:
        retry_claim = await events.find_one_and_update(
            {"invitee_uri": invitee_uri, "$or": [{"status": "failed"}, {"status": "processing", "lease_until": {"$lte": now}}]},
            {"$set": {"status": "processing", "lease_until": now + timedelta(minutes=5), "updated_at": now}},
            return_document=ReturnDocument.AFTER,
        )
        if not retry_claim:
            return {"received": True, "duplicate": True}

    phone_variants = phone_lookup_values(booking_phone)
    match_or = []
    if email:
        match_or.append({"email": {"$regex": f"^{re.escape(email)}$", "$options": "i"}})
    if phone_variants:
        match_or.append({"contact_number": {"$in": phone_variants}})
    contact = await state.contacts.find_one({"whatsapp_opt_in": True, "$or": match_or}) if match_or else None
    lead = None
    if not contact and match_or:
        lead_or = []
        if email:
            lead_or.append({"email": {"$regex": f"^{re.escape(email)}$", "$options": "i"}})
        if phone_variants:
            lead_or.extend([
                {"whatsapp_number": {"$in": phone_variants}},
                {"mobile_number": {"$in": phone_variants}},
            ])
        lead = await state.enquiries.find_one({"$or": lead_or}) if lead_or else None
    if not contact and not lead and match_or:
        contact = await state.contacts.find_one({"$or": match_or})
    matched = contact or lead
    if not matched:
        await events.update_one({"invitee_uri": invitee_uri}, {"$set": {"status": "unmatched"}, "$unset": {"lease_until": ""}})
        logger.warning(
            "Calendly booking %s was not matched to a contact or enquiry (email present: %s, phone present: %s)",
            invitee_uri,
            bool(email),
            bool(booking_phone),
        )
        return {"received": True, "matched": False, "notification_status": "unmatched"}

    def display_time(value: str) -> str:
        try:
            instant = datetime.fromisoformat(value.replace("Z", "+00:00"))
            timezone_name = str(payload.get("timezone", "UTC"))
            return instant.astimezone(ZoneInfo(timezone_name)).strftime("%a %d %b %Y, %I:%M %p %Z")
        except (ValueError, KeyError, ZoneInfoNotFoundError):
            return value or "Not provided"

    location = scheduled_event.get("location") or {}
    joining_url = location.get("join_url") or location.get("location") or CALENDLY_URL
    conversation = None
    for candidate in (
        (contact or {}).get("contact_number"),
        (lead or {}).get("whatsapp_number"),
        (lead or {}).get("mobile_number"),
        booking_phone,
    ):
        for variant in phone_lookup_values(candidate):
            conversation = await state.whatsapp_conversations.find_one({"phone": variant})
            if conversation:
                break
        if conversation:
            break
    recipient_phone = (
        (conversation or {}).get("phone")
        or (contact or {}).get("contact_number")
        or (lead or {}).get("whatsapp_number")
        or normalize_e164((lead or {}).get("mobile_number", ""))
        or booking_phone
    )
    window_open = booking_window_open(conversation)
    whatsapp_allowed = bool(
        (contact and contact.get("whatsapp_opt_in"))
        or (lead and lead.get("source") == "contact_us_whatsapp")
    )
    if conversation and conversation.get("status") == "stopped":
        notification_status = "opted_out"
    elif not whatsapp_allowed:
        notification_status = "not_opted_in"
    elif not recipient_phone:
        notification_status = "missing_phone"
    elif not window_open and not (BOOKING_TEMPLATE_SID or CALENDLY_BOOKING_TEMPLATE_SID):
        notification_status = "template_not_configured"
    else:
        notification_status = "queued"

    booking = {
        "invitee_uri": invitee_uri,
        "event_uri": str(payload.get("event", "")),
        "event_name": str(scheduled_event.get("name", "")),
        "invitee_name": str(payload.get("name", "")),
        "invitee_email": email,
        "invitee_phone": booking_phone,
        "start_time": scheduled_event.get("start_time"),
        "end_time": scheduled_event.get("end_time"),
        "timezone": str(payload.get("timezone", "UTC")),
        "location": location,
        "join_url": location.get("join_url", ""),
        "questions_and_answers": answers,
        "reschedule_url": payload.get("reschedule_url", ""),
        "cancel_url": payload.get("cancel_url", ""),
        "received_at": now,
        "notification": {"status": notification_status, "twilio_message_sid": None, "updated_at": now},
    }
    collection = state.contacts if contact else state.enquiries
    await collection.update_one({"_id": matched["_id"]}, {"$set": {"calendly_booking": booking}})
    await events.update_one(
        {"invitee_uri": invitee_uri},
        {"$set": {"status": notification_status}, "$unset": {"lease_until": ""}},
    )
    background_tasks.add_task(
        sync_zoho_lead,
        {
            **matched,
            "full_name": payload.get("name") or matched.get("full_name") or " ".join(
                part for part in (matched.get("first_name", ""), matched.get("last_name", "")) if part
            ),
            "email": email or matched.get("email", ""),
            "mobile_number": booking_phone or matched.get("mobile_number") or matched.get("contact_number", ""),
            "source": "Calendly booking",
            "local_id": str(matched.get("_id", "")),
            "calendly_event_name": booking["event_name"],
            "calendly_start_time": display_time(str(booking["start_time"] or "")),
            "calendly_join_url": booking["join_url"],
        },
    )
    logger.info(
        "Calendly booking %s matched; WhatsApp notification status=%s",
        invitee_uri,
        notification_status,
    )

    answers_summary = "; ".join(
        f"{str(item.get('question', '')).strip()}: {str(item.get('answer', '')).strip()}"
        for item in answers if isinstance(item, dict) and item.get("question") and item.get("answer")
    )
    booking_details = []
    memberships = scheduled_event.get("event_memberships") or []
    host_name = next((
        str(member.get("user_name") or (member.get("user", {}).get("name") if isinstance(member.get("user"), dict) else "") or "").strip()
        for member in memberships
        if isinstance(member, dict)
        and (member.get("user_name") or (member.get("user", {}).get("name") if isinstance(member.get("user"), dict) else ""))
    ), SENDER_NAME)
    event_start = display_time(str(booking["start_time"] or ""))
    event_end = display_time(str(booking["end_time"] or ""))
    timezone_name = booking["timezone"]
    if timezone_name in {"Asia/Kolkata", "Asia/Calcutta"}:
        timezone_label = "India Standard Time (IST)"
    else:
        try:
            timezone_label = f"{timezone_name} ({datetime.now(ZoneInfo(timezone_name)).tzname()})"
        except (ZoneInfoNotFoundError, ValueError):
            timezone_label = timezone_name
    booking_details.extend([
        f"Calendly booking details: {booking['event_name'] or 'Property meeting'}",
        f"Host: {host_name}",
        f"Date/time: {event_start} to {event_end}",
        f"Time zone: {timezone_label}",
        f"Phone: {booking_phone or 'Not provided'}",
    ])
    if booking["reschedule_url"]:
        booking_details.append(f"Reschedule: {booking['reschedule_url']}")
    if booking["cancel_url"]:
        booking_details.append(f"Cancel: {booking['cancel_url']}")
    if answers_summary:
        booking_details.append(f"Answers: {answers_summary}")
    template_variables = {
        "1": str(payload.get("name") or matched.get("full_name") or matched.get("first_name") or "there"),
        "2": str(booking["event_name"] or "Property meeting"),
        "3": display_time(str(booking["start_time"] or "")),
        "4": display_time(str(booking["end_time"] or "")),
        "5": booking["timezone"],
        "6": str(joining_url),
        "7": " | ".join(booking_details)[:900],
    }
    if notification_status == "queued":
        background_tasks.add_task(
            send_calendly_confirmation,
            events,
            collection,
            matched["_id"],
            invitee_uri,
            recipient_phone,
            template_variables,
            window_open,
        )
    return {"received": True, "matched": True, "notification_status": notification_status}


def phone_lookup_values(value: object) -> list[str]:
    """Match Calendly phones against stored E.164, +91, and 10-digit enquiry numbers."""
    raw = str(value or "").strip()
    digits = re.sub(r"\D", "", raw)
    e164 = normalize_e164(raw)
    variants = []
    for item in (e164, digits):
        if item and item not in variants:
            variants.append(item)
    if len(digits) >= 10:
        last10 = digits[-10:]
        for item in (last10, f"+{last10}", f"91{last10}", f"+91{last10}"):
            if item not in variants:
                variants.append(item)
    return variants


def normalize_e164(value: object) -> str:
    raw = str(value or "").strip()
    digits = re.sub(r"\D", "", raw)
    if raw.startswith("+") and 8 <= len(digits) <= 15 and digits[0] != "0":
        return f"+{digits}"
    return ""


async def send_calendly_confirmation(events, leads, lead_id, invitee_uri, recipient_phone, variables, window_open):
    """Send to the matched customer's number; TWILIO_WHATSAPP_FROM is the sender."""
    message_sid = await run_in_threadpool(
        send_booking_confirmation, recipient_phone, variables, window_open
    )
    status = "accepted" if message_sid else "failed"
    logger.info(
        "Calendly WhatsApp send for %s: status=%s, 24-hour window open=%s, Twilio SID present=%s",
        invitee_uri,
        status,
        window_open,
        bool(message_sid),
    )
    now = datetime.now(timezone.utc)
    await leads.update_one(
        {"_id": lead_id},
        {"$set": {
            "calendly_booking.notification.status": status,
            "calendly_booking.notification.twilio_message_sid": message_sid,
            "calendly_booking.notification.updated_at": now,
        }},
    )
    await events.update_one(
        {"invitee_uri": invitee_uri},
        {"$set": {"status": status, "twilio_message_sid": message_sid, "updated_at": now}},
    )
