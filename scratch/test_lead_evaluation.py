import re

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
        or " ".join(filter(None, [lead.get("first_name", ""), lead.get("last_name", "")]))
    ).strip()
    
    if not raw_name or len(raw_name) < 2:
        errors.append("Name is missing or too short (< 2 characters)")
    else:
        lower_name = raw_name.lower()
        for pat in DUMMY_NAME_PATTERNS:
            if re.search(pat, lower_name):
                errors.append(f"Name looks like test/dummy data ('{raw_name}')")
                break
        # Reject names with only digits or symbols
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
    phone_clean = re.sub(r"^whatsapp:", "", raw_phone, flags=re.IGNORECASE).strip()
    phone_digits = re.sub(r"\D", "", phone_clean)
    
    if not phone_digits:
        errors.append("Phone number is missing")
    elif len(phone_digits) < 10 or len(phone_digits) > 15:
        errors.append(f"Phone number has invalid length ({len(phone_digits)} digits)")
    else:
        # Check repetitive or dummy numbers (e.g., 0000000000, 1111111111)
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
                errors.append(f"Email domain '{domain}' is a dummy/test domain")

    return (len(errors) == 0, errors)

def evaluate_lead_quality(lead: dict) -> dict:
    """Score lead quality and determine if it meets HOT LEAD criteria."""
    is_valid, validation_errors = validate_lead_data(lead)
    
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
    
    # Trigger 1: Meeting scheduled via Calendly
    if calendly_event or lead.get("calendly_start_time"):
        score += 50
        triggers.append("Direct consultation meeting booked on Calendly")
        reasons.append(f"Meeting booked: {calendly_event or 'Advisor session'}")

    # Timeline scoring
    if planning in ["Immediately", "Within 1 Month"]:
        score += 40
        triggers.append(f"Urgent buying timeline: {planning}")
        reasons.append(f"Timeline: {planning} (+40)")
    elif planning == "Within 3 Months":
        score += 25
        reasons.append("Timeline: Within 3 Months (+25)")
    elif planning == "Within 6 Months":
        score += 15
        reasons.append("Timeline: Within 6 Months (+15)")
    elif planning in ["More Than 1 Year", "Just Exploring / Researching"]:
        score -= 10
        reasons.append(f"Low urgency timeline: {planning} (-10)")

    # Budget scoring
    if budget == "Above 2 crore":
        score += 30
        triggers.append("High budget segment: Above 2 crore")
        reasons.append("Budget: Above 2 crore (+30)")
    elif budget == "1 crore - 2 crore":
        score += 25
        triggers.append("High budget segment: 1 - 2 crore")
        reasons.append("Budget: 1 - 2 crore (+25)")
    elif budget == "50 lakh - 1 crore":
        score += 15
        reasons.append("Budget: 50 lakh - 1 crore (+15)")
    elif budget in ["25 lakh - 50 lakh", "Up to 25 lakh"]:
        score += 5
        reasons.append(f"Budget: {budget} (+5)")

    # Payment scoring
    if payment == "Full Cash Payment":
        score += 25
        triggers.append("Ready cash buyer (Full Cash Payment)")
        reasons.append("Payment: Full Cash Payment (+25)")
    elif "Cash" in payment:
        score += 15
        reasons.append(f"Payment: {payment} (+15)")
    elif "Loan" in payment or "Bank Finance" in payment:
        score += 10
        reasons.append("Payment: Bank / Home Loan (+10)")

    # Preference completeness
    if location and bhk:
        score += 10
        reasons.append(f"Defined property preference: {bhk} in {location} (+10)")

    # WhatsApp questionnaire completion
    if wa_answers and len(wa_answers) >= 3:
        score += 15
        reasons.append("Completed full WhatsApp qualification (+15)")

    # Bound score 0-100
    final_score = max(0, min(100, score))
    
    # A lead is HOT if:
    # 1. Has scheduled a meeting (Calendly), OR
    # 2. Buying immediately / within 1 month AND has budget, OR
    # 3. Cash buyer buying within 3 months, OR
    # 4. Total score >= 50
    is_hot = bool(
        (calendly_event or lead.get("calendly_start_time"))
        or (planning in ["Immediately", "Within 1 Month"] and budget)
        or (payment == "Full Cash Payment" and planning in ["Immediately", "Within 1 Month", "Within 3 Months"])
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

# Test cases
test_cases = [
    {
        "name": "Dummy Test User",
        "lead": {"full_name": "Test Integration User", "email": "test@example.com", "mobile_number": "+919876543210"}
    },
    {
        "name": "Hot Lead - Immediate Buyer 1Cr+",
        "lead": {
            "first_name": "Himanshu", "last_name": "Joshi",
            "email": "hj1903954@gmail.com", "mobile_number": "+918057858023",
            "location_preference": "Haldwani, Uttarakhand",
            "planning_to_buy": "Within 1 Month",
            "budget_range": "1 crore - 2 crore",
            "payment_option": "Part Cash + Home Loan",
            "bhk_preference": "3 BHK"
        }
    },
    {
        "name": "Hot Lead - Cash Buyer",
        "lead": {
            "first_name": "Rudra", "last_name": "Singh Deo",
            "email": "rudra@gmail.com", "mobile_number": "+919068978137",
            "location_preference": "Dehradun",
            "planning_to_buy": "Immediately",
            "budget_range": "50 lakh - 1 crore",
            "payment_option": "Full Cash Payment",
            "bhk_preference": "Villa"
        }
    },
    {
        "name": "Hot Lead - Booked Calendly Meeting",
        "lead": {
            "full_name": "Monu Bisht",
            "email": "monubisht@gmail.com", "mobile_number": "+919163988734",
            "calendly_event_name": "15 Minute Consultation",
            "calendly_start_time": "2026-10-30T10:00:00Z"
        }
    },
    {
        "name": "Cold Lead - Just Exploring raw contact",
        "lead": {
            "full_name": "Shailendra Singh",
            "email": "shailendra@gmail.com", "mobile_number": "+919876598765",
            "planning_to_buy": "Just Exploring / Researching",
            "budget_range": "Up to 25 lakh"
        }
    },
    {
        "name": "Raw Contact Form submission (No requirements)",
        "lead": {
            "full_name": "Aman Verma",
            "email": "aman@gmail.com", "mobile_number": "+919834567812"
        }
    }
]

for tc in test_cases:
    res = evaluate_lead_quality(tc["lead"])
    print(f"=== {tc['name']} ===")
    print(f"Valid: {res['is_valid']} (Errors: {res['validation_errors']})")
    print(f"Hot Lead: {res['is_hot']} | Rating: {res['rating']} | Status: {res['lead_status']} | Score: {res['score']}")
    print(f"Triggers: {res['triggers']}")
    print(f"Reasons: {res['reasons']}")
    print()

