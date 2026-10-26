"""Twilio WhatsApp questionnaire for Contact Us submissions."""
import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from fastapi import BackgroundTasks
from fastapi.responses import Response
from starlette.concurrency import run_in_threadpool
from twilio.rest import Client
from twilio.twiml.messaging_response import MessagingResponse

logger = logging.getLogger("uvicorn.error")
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
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
START_TEMPLATE_SID = os.getenv("TWILIO_WHATSAPP_START_TEMPLATE_SID", "").strip()
BOOKING_TEMPLATE_SID = os.getenv("TWILIO_WHATSAPP_BOOKING_TEMPLATE_SID", "").strip()
CUSTOMER_SERVICE_WINDOW = timedelta(hours=24)

# Approved WhatsApp appointment template. Placeholders: name, event, start, end,
# timezone, location/join URL, extra Calendly details.
BOOKING_CONFIRMATION_TEMPLATE_BODY = (
    "Profilent: Hi {{1}}, your {{3}} is confirmed for {{4}} to {{5}} ({{6}}). "
    "Booking email: {{2}}. Location or joining link: {{7}}. {{8}} Reply STOP to opt out."
)

def start_template_variables(full_name: str, email: str, phone: str) -> dict[str, str]:
    """Fill the approved start template with the customer's submitted details."""
    return {"1": full_name, "2": email, "3": phone}


def start_message_text(full_name: str, email: str, phone: str, requirement: str = "") -> str:
    """Build the in-session greeting and first location question."""
    message = (
        f"Hi {full_name}, thanks for your property enquiry. "
        f"We have your details: email {email} and phone {phone}. "
    )
    if requirement.strip():
        message += f"I noted that you are looking for: {requirement.strip()[:700]}. "
    return message + TEXT_PROMPTS["q5_location"]

def whatsapp_configuration() -> dict:
    public_origin = PUBLIC_BASE_URL.casefold()
    public_https_ready = (
        public_origin.startswith("https://")
        and "localhost" not in public_origin
        and "127.0.0.1" not in public_origin
    )
    settings = (
        ("TWILIO_ACCOUNT_SID", bool(re.fullmatch(r"AC[0-9a-fA-F]{32}", TWILIO_ACCOUNT_SID or ""))),
        ("TWILIO_AUTH_TOKEN", bool(TWILIO_AUTH_TOKEN and "replace_with" not in TWILIO_AUTH_TOKEN.casefold() and "<" not in TWILIO_AUTH_TOKEN)),
        ("TWILIO_WHATSAPP_FROM", bool(re.fullmatch(r"\+[1-9][0-9]{7,14}", TWILIO_WHATSAPP_FROM or ""))),
        ("TWILIO_WHATSAPP_START_TEMPLATE_SID", bool(re.fullmatch(r"HX[0-9a-fA-F]{32}", START_TEMPLATE_SID or ""))),
    )
    missing = [name for name, configured in settings if not configured]
    if re.sub(r"\D", "", TWILIO_WHATSAPP_FROM) == "14155238886":
        missing.append("registered WhatsApp sender (custom templates are unavailable in Sandbox)")
    return {
        "outbound_configured": not missing,
        "inbound_webhook_configured": bool(TWILIO_AUTH_TOKEN and public_https_ready),
        "missing_outbound_settings": missing,
        "inbound_webhook_url": f"{PUBLIC_BASE_URL}/webhooks/whatsapp" if PUBLIC_BASE_URL else "",
    }

LISTS = {
    "q6_planning": {
        "sid": os.getenv("TWILIO_LIST_PLANNING_SID", ""),
        "question": "When are you planning to buy?",
        "rows": [
            ("planning_immediately", "Immediately", "Immediately"),
            ("planning_1_month", "Within 1 Month", "Within 1 Month"),
            ("planning_3_months", "Within 3 Months", "Within 3 Months"),
            ("planning_6_months", "Within 6 Months", "Within 6 Months"),
            ("planning_12_months", "Within 12 Months", "Within 12 Months"),
            ("planning_over_1_year", "More Than 1 Year", "More Than 1 Year"),
            ("planning_exploring", "Just Exploring", "Just Exploring / Researching"),
        ],
    },
    "q7_budget": {
        "sid": os.getenv("TWILIO_LIST_BUDGET_SID", ""),
        "question": "What's your budget range?",
        "rows": [
            ("budget_25_lakh", "Up to 25 Lakh", "Up to 25 lakh"),
            ("budget_25_50_lakh", "25 - 50 Lakh", "25 lakh - 50 lakh"),
            ("budget_50_lakh_1_crore", "50 Lakh - 1 Crore", "50 lakh - 1 crore"),
            ("budget_1_2_crore", "1 - 2 Crore", "1 crore - 2 crore"),
            ("budget_over_2_crore", "Above 2 Crore", "Above 2 crore"),
        ],
    },
    "q8_category": {
        "sid": os.getenv("TWILIO_LIST_PAYMENT_CATEGORY_SID", ""),
        "question": "How would you like to pay? Choose a category:",
        "rows": [
            ("pay_loan", "Loan / Bank Finance", "Loan / Bank Finance"),
            ("pay_cash", "Cash / Down Payment", "Cash / Down Payment"),
            ("pay_developer", "Developer Plans", "Developer Plans"),
            ("pay_nri", "NRI Payment Plan", "NRI Payment Plan (for Overseas Buyers)"),
        ],
    },
    "q8_loan": {
        "sid": os.getenv("TWILIO_LIST_PAYMENT_LOAN_SID", ""),
        "question": "Choose your loan or bank-finance option:",
        "rows": [
            ("loan_bank_emi", "Bank Finance (EMI)", "Bank Finance with EMI"),
            ("loan_mortgage", "Home Loan (Mortgage)", "Home Loan (Mortgage)"),
            ("loan_part_cash", "Part Cash + Home Loan", "Part Cash + Home Loan"),
            ("loan_joint", "Joint Home Loan", "Joint Home Loan (Co-applicant Financing)"),
        ],
    },
    "q8_cash": {
        "sid": os.getenv("TWILIO_LIST_PAYMENT_CASH_SID", ""),
        "question": "Choose your cash or down-payment option:",
        "rows": [
            ("cash_full", "Full Cash Payment", "Full Cash Payment"),
            ("cash_down_payment", "Down Payment Plan", "Down Payment Plan"),
            ("cash_balance_registration", "Balance at Registration", "Part Payment with Balance at Registration"),
        ],
    },
    "q8_developer": {
        "sid": os.getenv("TWILIO_LIST_PAYMENT_DEVELOPER_SID", ""),
        "question": "Choose your developer payment plan:",
        "rows": [
            ("dev_clp", "Construction-Linked", "Construction-Linked Payment Plan (CLP)"),
            ("dev_plp", "Possession-Linked", "Possession-Linked Payment Plan (PLP)"),
            ("dev_installment", "Installment Plan", "Installment Payment Plan"),
            ("dev_financing", "Developer Financing", "Developer Financing"),
            ("dev_rent_to_own", "Rent-to-Own", "Rent-to-Own Scheme"),
            ("dev_subvention", "Subvention (Pre-EMI)", "Subvention Scheme (Developer Pays Pre-EMI)"),
            ("dev_flexible", "Flexible Payment Plan", "Flexible Payment Plan"),
        ],
    },
    "q9_bhk": {
        "sid": os.getenv("TWILIO_LIST_BHK_SID", ""),
        "question": "What type of home are you looking for?",
        "rows": [
            ("bhk_1_rk", "1 RK", "1 RK"),
            ("bhk_1", "1 BHK", "1 BHK"),
            ("bhk_2", "2 BHK", "2 BHK"),
            ("bhk_2_5", "2.5 BHK", "2.5 BHK"),
            ("bhk_3", "3 BHK", "3 BHK"),
            ("bhk_3_5", "3.5 BHK", "3.5 BHK"),
            ("bhk_4", "4 BHK", "4 BHK"),
            ("bhk_5_plus", "5 BHK+", "5 BHK+"),
            ("bhk_villa", "Villa", "Villa"),
            ("bhk_penthouse", "Penthouse", "Penthouse"),
        ],
    },
}

QUICK_REPLY_MOBILE_SID = os.getenv("TWILIO_QUICK_REPLY_MOBILE_SID", "")
_LIST_LOOKUPS = {
    stage: {
        "by_id": {row_id: (label, value) for row_id, label, value in menu["rows"]},
        "by_label": {label.casefold(): (label, value) for _, label, value in menu["rows"]},
    }
    for stage, menu in LISTS.items()
}

TEXT_PROMPTS = {
    "q1_first_name": "Hi! 👋 Let's find your perfect property. What's your *first name*?",
    "q2_last_name": "Thanks, {first_name}! And your *last name*? (Type *skip* to continue)",
    "q3_email": "Please share your *email address*.",
    "q3_email_invalid": "That doesn't look right. Please enter a valid email, e.g. name@example.com",
    "q4_mobile_other": "Please type another 10-digit number.",
    "q5_location": "Which *city or area* are you looking to buy in?",
    "q10_remarks": "Any *remarks or requirements* for your property search? (Type *skip* if none)",
}

STAGE_PROMPT = {
    "q1_first_name": "q1_first_name",
    "q2_last_name": "q2_last_name",
    "q3_email": "q3_email",
    "q4_mobile": "q4_mobile",
    "q4_mobile_other": "q4_mobile_other",
    "q5_location": "q5_location",
    "q6_planning": "q6_planning",
    "q7_budget": "q7_budget",
    "q8_category": "q8_category",
    "q8_loan": "q8_loan",
    "q8_cash": "q8_cash",
    "q8_developer": "q8_developer",
    "q9_bhk": "q9_bhk",
    "q10_remarks": "q10_remarks",
}


def twiml(message: str = "") -> Response:
    response = MessagingResponse()
    if message:
        response.message(message)
    return Response(str(response), media_type="application/xml")


def _phone_suffix(phone: str) -> str:
    return re.sub(r"\D", "", phone)[-4:]


def send_content(
    recipient_phone: str,
    content_sid: str,
    variables: dict | None = None,
    *,
    purpose: str = "template",
) -> str | None:
    """Send from the configured business sender to the customer's WhatsApp number."""
    content_sid = str(content_sid or "").strip()
    if not re.fullmatch(r"HX[0-9a-fA-F]{32}", content_sid):
        logger.error("WhatsApp template send skipped: Content SID is missing or malformed.")
        return None
    if not all((TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_WHATSAPP_FROM, content_sid)):
        logger.error("WhatsApp message skipped: Twilio credentials, sender, or Content SID is missing.")
        return
    try:
        client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        kwargs = {
            "from_": f"whatsapp:{TWILIO_WHATSAPP_FROM}",
            "to": f"whatsapp:{recipient_phone}",
            "content_sid": content_sid,
        }
        if variables:
            kwargs["content_variables"] = json.dumps(variables)
        message = client.messages.create(**kwargs)
        return message.sid
    except Exception as exc:
        logger.exception(
            "Could not send WhatsApp template (purpose=%s, content_sid_present=%s, "
            "variables_count=%s, twilio_error_code=%s, phone_suffix=%s)",
            purpose,
            bool(content_sid),
            len(variables or {}),
            getattr(exc, "code", None),
            _phone_suffix(recipient_phone),
        )
        return None


def send_text(to_phone: str, body: str) -> str | None:
    """Send an in-session WhatsApp message, used for the Twilio Sandbox."""
    if not all((TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_WHATSAPP_FROM, body)):
        logger.error("WhatsApp text skipped: Twilio credentials, sender, or message is missing.")
        return None
    try:
        client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        message = client.messages.create(
            from_=f"whatsapp:{TWILIO_WHATSAPP_FROM}",
            to=f"whatsapp:{to_phone}",
            body=body,
        )
        return message.sid
    except Exception as exc:
        err_msg = str(exc)
        if "ContentSid" in err_msg or getattr(exc, "code", None) in (21654, 92005, 63016, 63018):
            logger.warning(
                "WhatsApp text not sent (phone suffix=%s): 24h session is closed; customer must message first via prefill link (%s)",
                _phone_suffix(to_phone),
                err_msg.splitlines()[0] if err_msg else "ContentSid Required",
            )
        else:
            logger.warning(
                "Could not send WhatsApp text (phone suffix=%s): %s",
                _phone_suffix(to_phone),
                err_msg.splitlines()[0] if err_msg else str(exc),
            )
        return None


def send_content_or_text(
    recipient_phone: str,
    content_sid: str,
    fallback_text: str,
    variables: dict | None = None,
    *,
    purpose: str = "interactive_questionnaire",
) -> None:
    """Try an approved interactive message, then use an in-session text fallback."""
    if send_content(recipient_phone, content_sid, variables, purpose=purpose):
        return
    if fallback_text:
        send_text(recipient_phone, fallback_text)


def booking_confirmation_text(variables: dict) -> str:
    """Fill the appointment prompt with Calendly date, time, and timezone."""
    text = BOOKING_CONFIRMATION_TEMPLATE_BODY
    for key in ("1", "2", "3", "4", "5", "6", "7", "8"):
        text = text.replace("{{" + key + "}}", str(variables.get(key, "")).strip())
    return re.sub(r"[ \t]{2,}", " ", text).strip()


def booking_window_open(conversation: dict | None) -> bool:
    """True when the customer's last inbound WhatsApp message is still inside 24 hours."""
    if not conversation:
        return False
    # Meta WhatsApp 24-hour window requires an inbound customer message
    timestamp = conversation.get("last_inbound_at")
    if not timestamp:
        return False
    if getattr(timestamp, "tzinfo", None) is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - timestamp <= CUSTOMER_SERVICE_WINDOW


def send_booking_confirmation(recipient_phone: str, variables: dict, window_open: bool) -> str | None:
    """Send full booking details using an approved template or open-session text."""
    sender_digits = re.sub(r"\D", "", TWILIO_WHATSAPP_FROM)
    if sender_digits == "14155238886":
        # The Sandbox has only a small set of account-provided templates. A
        # hard-coded example Content SID is not guaranteed to belong to this
        # account, so send full booking details as free-form text only while
        # the customer's 24-hour service window is open.
        if window_open:
            return send_text(recipient_phone, booking_confirmation_text(variables))
        logger.error(
            "Sandbox booking confirmation skipped: the customer service window is closed; "
            "use a registered WhatsApp sender and an approved booking template."
        )
        return None
    if BOOKING_TEMPLATE_SID:
        message_sid = send_content(
            recipient_phone,
            BOOKING_TEMPLATE_SID,
            variables,
            purpose="booking_confirmation",
        )
        if message_sid or not window_open:
            return message_sid
        logger.warning("Calendly template send failed in an open customer-service window; trying text.")
    if window_open:
        return send_text(recipient_phone, booking_confirmation_text(variables))
    logger.error("Calendly confirmation skipped: approved booking template is not configured.")
    return None


async def start_questionnaire(
    conversations,
    phone: str,
    contact_id: str,
    background_tasks: BackgroundTasks,
    *,
    full_name: str = "",
    email: str = "",
    requirement: str = "",
):
    prior_conversation = await conversations.find_one({"phone": phone})
    sandbox_window_open = booking_window_open(prior_conversation)
    name_parts = full_name.strip().split(maxsplit=1)
    answers = {
        "full_name": full_name,
        "first_name": name_parts[0] if name_parts else "",
        "last_name": name_parts[1] if len(name_parts) > 1 else "",
        "email": email,
        "mobile_number": phone,
    }
    await conversations.update_one(
        {"phone": phone},
        {"$set": {
            "phone": phone,
            "contact_id": contact_id,
            # The contact form already collected name, email, and mobile.
            # Start the remaining questionnaire with the location preference.
            "stage": "q5_location",
            "answers": answers,
            "form_requirement": requirement.strip(),
            "requirement_messages": [requirement.strip()] if requirement.strip() else [],
            "status": "awaiting_location",
            "updated_at": datetime.now(timezone.utc),
        }},
        upsert=True,
    )
    is_sandbox = re.sub(r"\D", "", TWILIO_WHATSAPP_FROM) == "14155238886"
    if is_sandbox:
        # In Twilio Sandbox (+14155238886), proactive outbound messages without
        # a Meta-approved template throw 'ContentSid Required' (error 21654).
        # The web contact form immediately redirects the customer to WhatsApp
        # with 'Hi' prefilled. We set status to 'awaiting_customer_start' so the
        # questionnaire begins as soon as they tap Send.
        await conversations.update_one(
            {"phone": phone},
            {"$set": {"status": "awaiting_customer_start", "updated_at": datetime.now(timezone.utc)}},
        )
        return {"started": True, "status": "awaiting_customer_start"}

    configuration = whatsapp_configuration()
    if not configuration["outbound_configured"]:
        missing = configuration["missing_outbound_settings"]
        logger.error("WhatsApp start message skipped: configure %s in .env.", ", ".join(missing))
        await conversations.update_one(
            {"phone": phone},
            {"$set": {"status": "template_not_configured", "updated_at": datetime.now(timezone.utc)}},
        )
        return {"started": False, "status": "configuration_missing", "missing": missing}
    message_sid = await run_in_threadpool(
        send_content,
        phone,
        START_TEMPLATE_SID,
        start_template_variables(full_name, email, phone),
        purpose="questionnaire_start",
    )
    if not message_sid:
        await conversations.update_one(
            {"phone": phone},
            {"$set": {"status": "start_send_failed", "updated_at": datetime.now(timezone.utc)}},
        )
        return {"started": False, "status": "twilio_rejected"}
    await conversations.update_one(
        {"phone": phone},
        {"$set": {"status": "awaiting_location", "start_message_sid": message_sid, "updated_at": datetime.now(timezone.utc)}},
    )
    return {"started": True, "status": "accepted"}


def menu_fallback(stage: str) -> str:
    menu = LISTS[stage]
    rows = menu["rows"]
    choices = "\n".join(f"{i}. {title}" for i, (_, title, _) in enumerate(rows, 1))
    return f"{menu['question']}\n{choices}\n\nReply with the option number."


def dispatch_stage(stage: str, phone: str, answers: dict, background_tasks: BackgroundTasks) -> str:
    if stage in LISTS:
        content_sid = LISTS[stage]["sid"]
        if content_sid:
            background_tasks.add_task(
                send_content_or_text,
                phone,
                content_sid,
                menu_fallback(stage),
                purpose=stage,
            )
            return ""
        return menu_fallback(stage)
    if stage == "q4_mobile":
        if QUICK_REPLY_MOBILE_SID:
            background_tasks.add_task(
                send_content_or_text,
                phone,
                QUICK_REPLY_MOBILE_SID,
                f"Is *{phone}* the best number to reach you? Reply *Yes*, or type another 10-digit number.",
                {"1": phone},
                purpose="mobile_confirmation",
            )
            return ""
        return f"Is *{phone}* the best number to reach you? Reply *Yes*, or type another 10-digit number."
    prompt_key = STAGE_PROMPT.get(stage)
    if not prompt_key:
        return ""
    if stage == "q2_last_name":
        return TEXT_PROMPTS[prompt_key].format(first_name=answers.get("first_name", "there"))
    return TEXT_PROMPTS[prompt_key]


def list_choice(stage: str, form) -> tuple[str, str] | None:
    menu = LISTS[stage]
    lookups = _LIST_LOOKUPS[stage]
    for candidate in (
        str(form.get("ButtonPayload", "")).strip(),
        str(form.get("Body", "")).strip(),
        str(form.get("ButtonText", "")).strip(),
    ):
        if candidate in lookups["by_id"]:
            return lookups["by_id"][candidate]
        if candidate.casefold() in lookups["by_label"]:
            return lookups["by_label"][candidate.casefold()]
        if candidate.isdigit():

            index = int(candidate) - 1

            if 0 <= index < len(menu["rows"]):

                _, label, value = menu["rows"][index]

                return label, value

    return None





def find_list_stage(stage: str) -> str | None:

    if stage in LISTS:

        return stage

    return None





def next_after_preferences(stage: str) -> str:

    return {

        "q8_loan": "q9_bhk",

        "q8_cash": "q9_bhk",

        "q8_developer": "q9_bhk",

    }[stage]
