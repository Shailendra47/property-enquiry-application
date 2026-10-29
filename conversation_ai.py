"""Hybrid Conversational AI Engine powered by OpenAI for WhatsApp property qualification.

Features:
- Natural, realistic conversational real-estate advisor persona for Profilent.
- Smart slot extraction for all 6 core criteria:
  (location_preference, bhk_preference, budget_range, planning_to_buy, payment_option, remarks_requirements).
- Hybrid UI: Pairs natural AI dialogue with clean quick-reply choices when prompting for
  structured fields (budget, timeline, BHK, payment).
- Resilient fallback: Automatically and transparently falls back to the deterministic state machine
  if OpenAI credentials have exhausted quota (HTTP 429) or suffer transient network downtime.
- Full downstream integration: Directly triggers MongoDB Atlas storage, Zoho CRM Leads upsert,
  salesperson notifications, and Calendly appointment booking.
"""

import json
import logging
import os
import re
from datetime import datetime, timezone
import time

import requests
from dotenv import load_dotenv
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from whatsapp_bot import build_prefilled_calendly_url, format_completion_summary_message

load_dotenv()

logger = logging.getLogger("uvicorn.error")

# Global reusable session with keep-alive and connection pooling
_ai_session = requests.Session()
_ai_adapter = HTTPAdapter(
    pool_connections=5,
    pool_maxsize=10,
    max_retries=Retry(total=1, backoff_factor=0.2, status_forcelist=[502, 503, 504], raise_on_status=False),
)
_ai_session.mount("https://", _ai_adapter)
_ai_session.mount("http://", _ai_adapter)

# Circuit breaker for 429 quota exhaustion (cool-down period in seconds)
_openai_cooldown_until = 0.0
_last_env_check = 0.0
_cached_openai_key = ""
_cached_openai_model = "gpt-4o-mini"
_cached_gemini_key = ""
_cached_gemini_model = "gemini-3.5-flash-lite"


def _get_gemini_config() -> tuple[str, str]:
    """Retrieve dynamic Gemini settings from environment with low-overhead caching."""
    global _last_env_check, _cached_gemini_key, _cached_gemini_model
    now = time.monotonic()
    if now - _last_env_check > 5.0 or not _cached_gemini_key:
        load_dotenv(override=False)
        _cached_gemini_key = os.getenv("GEMINI_API_KEY", "").strip()
        raw_model = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite").strip() or "gemini-3.5-flash-lite"
        _cached_gemini_model = raw_model
        _last_env_check = now
    return _cached_gemini_key, _cached_gemini_model


def _get_openai_config() -> tuple[str, str]:
    """Retrieve dynamic OpenAI settings from environment with low-overhead caching."""
    global _last_env_check, _cached_openai_key, _cached_openai_model
    now = time.monotonic()
    if now - _last_env_check > 5.0 or not _cached_openai_key:
        load_dotenv(override=False)
        _cached_openai_key = os.getenv("OPENAI_API_KEY", "").strip()
        _cached_openai_model = os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip() or "gpt-4o-mini"
        _last_env_check = now
    return _cached_openai_key, _cached_openai_model


def is_ai_configured() -> bool:
    """Check if Google Gemini or OpenAI API key is present."""
    g_key, _ = _get_gemini_config()
    if g_key and not g_key.startswith("replace_with"):
        return True
    o_key, _ = _get_openai_config()
    return bool(o_key and not o_key.startswith("replace_with"))


STANDARD_OPTIONS = {
    "location_preference": [
        "Haldwani (Rampur Rd, Kaladhungi Rd, Bithoria, Mukhani)",
        "Nainital / Bhimtal",
        "Almora",
        "Other (please type the area)",
    ],
    "planning_to_buy": [
        "Within 1 month",
        "1 to 3 months",
        "3 to 6 months",
        "Just exploring",
    ],
    "budget_range": [
        "Below ₹30 lakh",
        "₹30 lakh to ₹50 lakh",
        "₹50 lakh to ₹80 lakh",
        "₹80 lakh to ₹1 crore",
        "Above ₹1 crore",
    ],
    "payment_option": [
        "Full payment",
        "Home loan",
        "Combination of savings and loan",
        "Not decided yet",
    ],
    "bhk_preference": [
        "1 BHK",
        "2 BHK",
        "3 BHK",
        "4 BHK or more",
        "Not sure",
    ],
}

QUESTION_PROMPTS_MULTILINGUAL = {
    "en": {
        "location_preference": (
            "Which area are you interested in?\n"
            "1. Haldwani (Rampur Rd, Kaladhungi Rd, Bithoria, Mukhani)\n"
            "2. Nainital / Bhimtal\n"
            "3. Almora\n"
            "4. Other (please type the area)"
        ),
        "planning_to_buy": (
            "What is your timeline?\n"
            "1. Within 1 month\n"
            "2. 1 to 3 months\n"
            "3. 3 to 6 months\n"
            "4. Just exploring"
        ),
        "budget_range": (
            "What is your budget?\n"
            "1. Below ₹30 lakh\n"
            "2. ₹30 lakh to ₹50 lakh\n"
            "3. ₹50 lakh to ₹80 lakh\n"
            "4. ₹80 lakh to ₹1 crore\n"
            "5. Above ₹1 crore"
        ),
        "payment_option": (
            "How do you plan to pay?\n"
            "1. Full payment\n"
            "2. Home loan\n"
            "3. Combination of savings and loan\n"
            "4. Not decided yet"
        ),
        "bhk_preference": (
            "Which configuration do you need?\n"
            "1. 1 BHK\n"
            "2. 2 BHK\n"
            "3. 3 BHK\n"
            "4. 4 BHK or more\n"
            "5. Not sure"
        ),
        "remarks_requirements": (
            "Do you have any other requirements, such as parking, floor preference, facing direction, or nearby schools or offices? Type \"skip\" if none."
        ),
        "skip_warning": "Please answer this question before we move on:\n\n",
        "inappropriate": (
            "I am here to assist you exclusively with finding the best properties and real estate opportunities in Haldwani & Uttarakhand. 🏡\n\n"
            "Let's focus on your property search!\n\n"
        ),
    },
    "hinglish": {
        "location_preference": (
            "Aap kis area me property dekh rahe hain?\n"
            "1. Haldwani (Rampur Rd, Kaladhungi Rd, Bithoria, Mukhani)\n"
            "2. Nainital / Bhimtal\n"
            "3. Almora\n"
            "4. Other (apna area type karein)"
        ),
        "planning_to_buy": (
            "Aapka timeline kya hai (kab tak lena chahte hain)?\n"
            "1. 1 month ke andar\n"
            "2. 1 se 3 months\n"
            "3. 3 se 6 months\n"
            "4. Just exploring"
        ),
        "budget_range": (
            "Aapka budget kitna hai?\n"
            "1. ₹30 lakh se kam\n"
            "2. ₹30 lakh se ₹50 lakh\n"
            "3. ₹50 lakh se ₹80 lakh\n"
            "4. ₹80 lakh se ₹1 crore\n"
            "5. ₹1 crore se zyada"
        ),
        "payment_option": (
            "Aap payment kaise plan kar rahe hain?\n"
            "1. Full payment (self-funding)\n"
            "2. Home loan\n"
            "3. Savings aur loan dono mila ke\n"
            "4. Abhi decide nahi kiya"
        ),
        "bhk_preference": (
            "Aapko kitne BHK ki requirement hai?\n"
            "1. 1 BHK\n"
            "2. 2 BHK\n"
            "3. 3 BHK\n"
            "4. 4 BHK ya usse zyada\n"
            "5. Not sure"
        ),
        "remarks_requirements": (
            "Kya aapki koi aur requirement hai jaise parking, floor, facing, ya schools/offices ke paas? Agar nahi hai toh \"skip\" type karein."
        ),
        "skip_warning": "Aage badhne se pehle please is sawaal ka jawab dein:\n\n",
        "inappropriate": (
            "Main yahan Haldwani aur Uttarakhand me best property dhoondhne me aapki madad karne ke liye hoon. 🏡\n\n"
            "Aaiye aapki property search pe focus karte hain!\n\n"
        ),
    },
    "hi": {
        "location_preference": (
            "आप किस इलाके में प्रॉपर्टी देख रहे हैं?\n"
            "1. हल्द्वानी (रामपुर रोड, कालाढूंगी रोड, बिठौरिया, मुखानी)\n"
            "2. नैनीताल / भीमताल\n"
            "3. अल्मोड़ा\n"
            "4. अन्य (कृपया इलाके का नाम लिखें)"
        ),
        "planning_to_buy": (
            "आपकी समयसीमा क्या है (कब तक प्रॉपर्टी लेना चाहते हैं)?\n"
            "1. 1 महीने के भीतर\n"
            "2. 1 से 3 महीने में\n"
            "3. 3 से 6 महीने में\n"
            "4. अभी सिर्फ जानकारी ले रहे हैं"
        ),
        "budget_range": (
            "आपका बजट कितना है?\n"
            "1. ₹30 लाख से कम\n"
            "2. ₹30 लाख से ₹50 लाख\n"
            "3. ₹50 लाख से ₹80 लाख\n"
            "4. ₹80 लाख से ₹1 करोड़\n"
            "5. ₹1 करोड़ से अधिक"
        ),
        "payment_option": (
            "आप भुगतान किस प्रकार करने की योजना बना रहे हैं?\n"
            "1. पूरा नकद भुगतान (Full payment)\n"
            "2. होम लोन (Home loan)\n"
            "3. बचत और लोन दोनों मिलाकर\n"
            "4. अभी तय नहीं किया"
        ),
        "bhk_preference": (
            "आपको किस कॉन्फ़िगरेशन (BHK) की आवश्यकता है?\n"
            "1. 1 BHK\n"
            "2. 2 BHK\n"
            "3. 3 BHK\n"
            "4. 4 BHK या अधिक\n"
            "5. निश्चित नहीं"
        ),
        "remarks_requirements": (
            "क्या आपकी कोई अन्य आवश्यकता है, जैसे पार्किंग, फ्लोर, दिशा (facing) या स्कूल/ऑफिस के पास? यदि कुछ नहीं तो \"skip\" टाइप करें।"
        ),
        "skip_warning": "आगे बढ़ने से पहले कृपया इस प्रश्न का उत्तर दें:\n\n",
        "inappropriate": (
            "मैं यहां हल्द्वानी और उत्तराखंड में बेहतरीन प्रॉपर्टी ढूंढने में आपकी सहायता के लिए हूं। 🏡\n\n"
            "आइए आपकी प्रॉपर्टी खोज पर ध्यान केंद्रित करते हैं!\n\n"
        ),
    },
}

QUESTION_PROMPTS = QUESTION_PROMPTS_MULTILINGUAL["en"]

ORDERED_REQUIRED_SLOTS = [
    "location_preference",
    "planning_to_buy",
    "budget_range",
    "payment_option",
    "bhk_preference",
]

_SPEAK_TO_HUMAN_PATTERN = re.compile(
    r"\b(speak to (?:a )?(?:person|human|executive|agent|representative|someone)|"
    r"talk to (?:a )?(?:person|human|executive|agent|representative|someone)|"
    r"call me|human agent|sales executive|connect (?:me )?to (?:a )?(?:person|human|executive|agent)|"
    r"human|person chahiye|agent se baat|executive se baat|baat karni hai|call karo|insan se baat|"
    r"बात करनी है|कॉल करो|कॉल करें|एजेंट से बात|इंसान से बात|कॉल कीजिए)\b",
    re.IGNORECASE,
)

_HINGLISH_WORDS = re.compile(
    r"\b(mujhe|chahiye|aap|aapka|aapko|hai|hain|kya|bhai|karna|hoga|batao|bataiye|"
    r"kitna|kitne|mein?|se|ke|liye|ka|ki|ko|nahi|nahin|dhanyawad|ghar|makan|zameen|"
    r"raha|rahe|karein|bhi|aur|kaun|kaunsa|kab|tak|dekh|baat|karo|shukriya|namaste|namaskar)\b",
    re.IGNORECASE,
)

_HINDI_NUMS = {"१": 1, "२": 2, "३": 3, "४": 4, "५": 5}


def detect_language(text: str, current_lang: str = "en") -> str:
    """Detect whether user text is in Hindi (Devanagari), Hinglish (Romanized Hindi), or English."""
    if not text:
        return current_lang
    if re.search(r"[\u0900-\u097F]", text):
        return "hi"
    if _HINGLISH_WORDS.search(text):
        return "hinglish"
    # Pure numbers, punctuation, or generic 'skip' should preserve the current language
    if re.match(r"^[\s\d\.\,\#\-\(\)\/\:]+$", text) or text.strip().lower() in {"skip", "ok", "yes", "no"}:
        return current_lang
    return current_lang


def get_question_prompt(slot: str, lang: str = "en") -> str:
    """Retrieve localized question prompt for the given slot."""
    prompts = QUESTION_PROMPTS_MULTILINGUAL.get(lang, QUESTION_PROMPTS_MULTILINGUAL["en"])
    return prompts.get(slot, QUESTION_PROMPTS_MULTILINGUAL["en"].get(slot, ""))


def _resolve_numbered_choice(user_message: str, slot: str) -> str | None:
    """Resolve a 1-5 numerical reply (including Hindi numerals १-५) to the corresponding question option."""
    txt = user_message.strip()
    match = re.match(r"^(?:option\s*|#\s*|no\.?\s*|number\s*)?([1-5१-५])[\.\)]?(?:\s*(?:bhk|st|nd|rd|th|number))?$", txt, re.IGNORECASE)
    if not match:
        return None
    raw_digit = match.group(1)
    num_val = _HINDI_NUMS.get(raw_digit, None) or int(raw_digit)
    idx = num_val - 1
    options = STANDARD_OPTIONS.get(slot, [])
    if 0 <= idx < len(options):
        return options[idx]
    return None


def _format_bullet_options(options: list[str]) -> str:
    """Format options as clean, modern WhatsApp bullet points."""
    return "\n".join(f"• {opt}" for opt in options)


def _strip_repetitive_greetings(text: str) -> str:
    """Strip repetitive 'Namaste [Name] ji!', 'Hi [Name]!', 'Hello [Name]!' from assistant responses."""
    if not text:
        return text

    # 1. Pattern: 'Namaste [Name] ji!' or 'Namaste [Name]!' or 'Namaste ji!' or 'Namaste!'
    p1 = r"^(?:namaste|namaskar|hello|hi|hey|greetings|welcome)(?:\s+[\w\s]{1,40}?(?:\s+ji|\bji)?)?\s*[\!.,:\-–—]\s*"
    text = re.sub(p1, "", text, flags=re.IGNORECASE).strip()

    # 2. Pattern: 'Wonderful, Shailendra deo ji! ' -> 'Wonderful! '
    p2 = r"^(wonderful|great|perfect|excellent|fantastic|got it|sure|thank you|thanks)\s*,\s*[\w\s]{1,40}?(?:\s+ji|\bji)?\s*[\!.,:\-–—]\s*"
    text = re.sub(p2, r"\1! ", text, flags=re.IGNORECASE).strip()

    # 3. Clean any remaining standalone leading 'Namaste' or 'Namaste ji' without punctuation
    text = re.sub(r"^(?:namaste|namaskar|hello|hi|hey)\s*(?:ji)?\s+", "", text, flags=re.IGNORECASE).strip()

    if text and text[0].islower():
        text = text[0].upper() + text[1:]

    return text


def _get_calendly_schedule_block(cal_url: str, lang: str = "en") -> str:
    """Return a prominent localized Calendly scheduling call-to-action block."""
    if lang == "hi":
        return (
            "🗓️ अपनी सुविधानुसार 1-on-1 परामर्श शेड्यूल करें:\n"
            f"{cal_url}"
        )
    elif lang == "hinglish":
        return (
            "🗓️ Apni suvidha ke anusaar 1-on-1 consultation schedule karein:\n"
            f"{cal_url}"
        )
    else:
        return (
            "🗓️ Schedule a 1-on-1 consultation at your convenience:\n"
            f"{cal_url}"
        )


def _build_system_prompt(first_name: str, known_criteria: dict, is_followup: bool = False, schedule_url: str = "") -> str:
    """Build natural conversational qualification prompt matching the Profilent specification."""
    fn = (first_name.split()[0] if first_name else "there").strip()
    booking_url = schedule_url or os.getenv("CALENDLY_URL", "https://calendly.com/shailendra-profilent/30min")
    if is_followup:
        return (
            f"You are a friendly real estate enquiry assistant for Profilent. You are assisting {fn} on WhatsApp.\n\n"
            f"STATUS: The customer has already completed their property questionnaire.\n"
            f"Current Known Criteria:\n{json.dumps(known_criteria, indent=2)}\n\n"
            f"RULES:\n"
            f"- DO NOT repeat greetings on every turn (no 'Namaste [Name]', 'Hi [Name]' on subsequent turns).\n"
            f"- Keep replies short and in the customer's language (English, Hindi, or Hinglish, based on how they write. If they speak Hindi or Hinglish, reply in Hindi or Hinglish respectively).\n"
            f"- Don't quote prices, availability, or loan terms. Say that a sales executive will confirm these.\n"
            f"- If customer asks to speak to a person, say that a sales executive will call them.\n"
            f"- In closing, confirming, or acknowledging messages, or when the customer wants to schedule a meeting or site visit, provide this Calendly link: {booking_url}\n"
            f"- CRITICAL: DO NOT invent fake site visits, property addresses, morning/afternoon/evening time slots, or ask for alternate phone numbers yourself. All scheduling and site visits must be directed to Calendly: {booking_url}\n"
            f"- If customer sends inappropriate or offensive messages, politely steer back to real estate.\n"
            f"- Keep 'is_complete': false so the conversation remains active.\n\n"
            f"Output MUST be a valid JSON object matching this schema:\n"
            f"{{\n"
            f'  "extracted_slots": {{\n'
            f'    "location_preference": "...",\n'
            f'    "planning_to_buy": "...",\n'
            f'    "budget_range": "...",\n'
            f'    "payment_option": "...",\n'
            f'    "bhk_preference": "...",\n'
            f'    "remarks_requirements": "..."\n'
            f"  }},\n"
            f'  "reply_message": "...",\n'
            f'  "is_complete": false\n'
            f"}}"
        )

    return (
        f"You are a friendly real estate enquiry assistant for Profilent. Your job is to collect the customer's property requirements, one question at a time, and then summarise them for the sales team. You are assisting {fn} on WhatsApp.\n\n"
        f"Ask the questions in this order. For each question, show the numbered options and let the customer reply with a number or their own words. Accept an answer if it's clear, even if it doesn't match an option exactly.\n\n"
        f"1. Location Preference (required)\n"
        f"   Which area are you interested in?\n"
        f"   1. Haldwani (Rampur Rd, Kaladhungi Rd, Bithoria, Mukhani)\n"
        f"   2. Nainital / Bhimtal\n"
        f"   3. Almora\n"
        f"   4. Other (please type the area)\n\n"
        f"2. Planning to Buy (required)\n"
        f"   What is your timeline?\n"
        f"   1. Within 1 month\n"
        f"   2. 1 to 3 months\n"
        f"   3. 3 to 6 months\n"
        f"   4. Just exploring\n\n"
        f"3. Budget Range (required)\n"
        f"   What is your budget?\n"
        f"   1. Below ₹30 lakh\n"
        f"   2. ₹30 lakh to ₹50 lakh\n"
        f"   3. ₹50 lakh to ₹80 lakh\n"
        f"   4. ₹80 lakh to ₹1 crore\n"
        f"   5. Above ₹1 crore\n\n"
        f"4. Payment Option (required)\n"
        f"   How do you plan to pay?\n"
        f"   1. Full payment\n"
        f"   2. Home loan\n"
        f"   3. Combination of savings and loan\n"
        f"   4. Not decided yet\n\n"
        f"5. BHK Preference (required)\n"
        f"   Which configuration do you need?\n"
        f"   1. 1 BHK\n"
        f"   2. 2 BHK\n"
        f"   3. 3 BHK\n"
        f"   4. 4 BHK or more\n"
        f"   5. Not sure\n\n"
        f"6. Remarks/Requirements (optional)\n"
        f"   Do you have any other requirements, such as parking, floor preference, facing direction, or nearby schools or offices? Type \"skip\" if none.\n\n"
        f"Rules:\n"
        f"- Ask only one question per message.\n"
        f"- Required fields must be answered before you move on. If the customer skips one, politely ask again.\n"
        f"- Don't quote prices, availability, or loan terms. Say that a sales executive will confirm these.\n"
        f"- Keep replies short and in the customer's language (English, Hindi, or Hinglish, based on how they write. If they speak Hindi or Hinglish, reply in Hindi or Hinglish respectively).\n"
        f"- If the customer asks to speak to a person, say that a sales executive will call them and move to the summary.\n"
        f"- DO NOT repeat greetings on every turn (no 'Namaste [Name]' or 'Hi [Name]' on subsequent turns).\n"
        f"- In the final summary or closing message, include this Calendly link to schedule a meeting: {booking_url}\n"
        f"- If the customer sends inappropriate, abusive, or nonsensical messages, politely steer back to the property enquiry.\n\n"
        f"Current Known Criteria:\n{json.dumps(known_criteria, indent=2)}\n\n"
        f"When all answers are collected (or if customer asks to speak to a person), set 'is_complete': true.\n\n"
        f"Output MUST be a valid JSON object matching this schema:\n"
        f"{{\n"
        f'  "extracted_slots": {{\n'
        f'    "location_preference": "...",\n'
        f'    "planning_to_buy": "...",\n'
        f'    "budget_range": "...",\n'
        f'    "payment_option": "...",\n'
        f'    "bhk_preference": "...",\n'
        f'    "remarks_requirements": "..."\n'
        f"  }},\n"
        f'  "reply_message": "...",\n'
        f'  "is_complete": true | false\n'
        f"}}"
    )


def _extract_json_object(raw: str) -> dict | None:
    """Robustly extract and parse a JSON object from LLM response text."""
    if not raw:
        return None
    cleaned = raw.strip()
    if cleaned.startswith("```json"):
        cleaned = cleaned[7:]
    elif cleaned.startswith("```"):
        cleaned = cleaned[3:]
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3]
    cleaned = cleaned.strip()
    try:
        return json.loads(cleaned)
    except Exception:
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except Exception:
                pass
    return None


def call_gemini_agent(
    user_message: str,
    current_answers: dict,
    recent_messages: list,
    contact_info: dict,
    is_followup: bool = False,
    schedule_url: str = "",
) -> dict | None:
    """Send conversation context to Google Gemini and return structured slots and reply."""
    api_key, model_name = _get_gemini_config()
    if not api_key:
        return None

    fn = contact_info.get("first_name") or current_answers.get("first_name") or ""
    if not fn:
        full_name = contact_info.get("full_name") or current_answers.get("full_name") or "there"
        fn = full_name.split()[0] if full_name else "there"
    known_criteria = {
        "location_preference": current_answers.get("location_preference") or "",
        "bhk_preference": current_answers.get("bhk_preference") or "",
        "budget_range": current_answers.get("budget_range") or "",
        "planning_to_buy": current_answers.get("planning_to_buy") or "",
        "payment_option": current_answers.get("payment_option") or "",
        "remarks_requirements": current_answers.get("remarks_requirements") or "",
    }
    safe_user_message = re.sub(r"\b[^\s@]+@[^\s@]+\.[^\s@]+\b", "[email hidden]", user_message)
    safe_user_message = re.sub(r"(?<!\w)\+?[\d][\d\s().-]{7,}[\d]", "[phone hidden]", safe_user_message)

    system_prompt = _build_system_prompt(fn, known_criteria, is_followup=is_followup, schedule_url=schedule_url)

    contents = []
    for msg in recent_messages[-6:]:
        role = "model" if msg.get("role") == "assistant" else "user"
        content = (msg.get("content") or "").strip()
        if content:
            if contents and contents[-1]["role"] == role:
                contents[-1]["parts"][0]["text"] += f"\n{content}"
            else:
                contents.append({"role": role, "parts": [{"text": content}]})

    if contents and contents[-1]["role"] == "user":
        contents[-1]["parts"][0]["text"] += f"\n{safe_user_message}"
    else:
        contents.append({"role": "user", "parts": [{"text": safe_user_message}]})

    payload = {
        "systemInstruction": {"parts": [{"text": system_prompt}]},
        "contents": contents,
        "generationConfig": {
            "responseMimeType": "application/json",
            "temperature": 0.3,
            "maxOutputTokens": 600,
        },
    }

    models_to_try = [model_name]
    for alt in ["gemini-3.5-flash-lite", "gemini-3.5-flash", "gemma-4-26b-a4b-it"]:
        if alt not in models_to_try:
            models_to_try.append(alt)

    for current_model in models_to_try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{current_model}:generateContent?key={api_key}"
        try:
            response = _ai_session.post(
                url,
                headers={"Content-Type": "application/json"},
                json=payload,
                timeout=12,
            )
            if not response.ok:
                logger.warning("Gemini model %s returned HTTP %s", current_model, response.status_code)
                continue
            body = response.json()
            raw_text = (
                body.get("candidates", [])[0]
                .get("content", {})
                .get("parts", [{}])[0]
                .get("text", "")
                .strip()
            )
            parsed = _extract_json_object(raw_text)
            if parsed:
                return parsed
        except Exception as exc:
            logger.warning("Gemini model %s call failed: %s", current_model, exc)
            continue

    return None


def call_openai_agent(
    user_message: str,
    current_answers: dict,
    recent_messages: list,
    contact_info: dict,
    is_followup: bool = False,
    schedule_url: str = "",
) -> dict | None:
    """Send conversation context to OpenAI and return structured slots and reply."""
    global _openai_cooldown_until
    if time.monotonic() < _openai_cooldown_until:
        return None

    api_key, model_name = _get_openai_config()
    if not api_key:
        return None

    fn = contact_info.get("first_name") or current_answers.get("first_name") or ""
    if not fn:
        full_name = contact_info.get("full_name") or current_answers.get("full_name") or "there"
        fn = full_name.split()[0] if full_name else "there"
    known_criteria = {
        "location_preference": current_answers.get("location_preference") or "",
        "bhk_preference": current_answers.get("bhk_preference") or "",
        "budget_range": current_answers.get("budget_range") or "",
        "planning_to_buy": current_answers.get("planning_to_buy") or "",
        "payment_option": current_answers.get("payment_option") or "",
        "remarks_requirements": current_answers.get("remarks_requirements") or "",
    }
    safe_user_message = re.sub(r"\b[^\s@]+@[^\s@]+\.[^\s@]+\b", "[email hidden]", user_message)
    safe_user_message = re.sub(r"(?<!\w)\+?[\d][\d\s().-]{7,}[\d]", "[phone hidden]", safe_user_message)

    system_prompt = _build_system_prompt(fn, known_criteria, is_followup=is_followup, schedule_url=schedule_url)

    formatted_messages = [{"role": "system", "content": system_prompt}]
    for msg in recent_messages[-6:]:
        role = "assistant" if msg.get("role") == "assistant" else "user"
        content = msg.get("content", "")
        if content:
            formatted_messages.append({"role": role, "content": content})

    formatted_messages.append({"role": "user", "content": safe_user_message})

    payload = {
        "model": model_name,
        "messages": formatted_messages,
        "response_format": {"type": "json_object"},
        "temperature": 0.4,
        "max_tokens": 500,
    }

    try:
        response = _ai_session.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=10,
        )

        if response.status_code == 429:
            _openai_cooldown_until = time.monotonic() + 45.0
            err = response.json().get("error", {})
            logger.warning(
                "OpenAI API quota exceeded or rate-limited (HTTP 429: %s).",
                err.get("message", "insufficient_quota"),
            )
            return None

        if not response.ok:
            logger.warning("OpenAI API call returned HTTP %s: %s", response.status_code, response.text[:200])
            return None

        body = response.json()
        choice = body.get("choices", [{}])[0]
        raw_content = choice.get("message", {}).get("content", "").strip()
        return json.loads(raw_content)

    except requests.RequestException as exc:
        logger.warning("OpenAI connection failed (%s); checking fallback.", exc)
        return None
    except Exception as exc:
        logger.exception("Unexpected error parsing OpenAI response: %s", exc)
        return None


def call_ai_agent(
    user_message: str,
    current_answers: dict,
    recent_messages: list,
    contact_info: dict,
    is_followup: bool = False,
    schedule_url: str = "",
) -> dict | None:
    """Intelligently route to Google Gemini first, with seamless fallback to OpenAI."""
    # 1. Primary: Google Gemini
    gemini_key, _ = _get_gemini_config()
    if gemini_key:
        result = call_gemini_agent(user_message, current_answers, recent_messages, contact_info, is_followup=is_followup, schedule_url=schedule_url)
        if result:
            return result

    # 2. Secondary: OpenAI
    openai_key, _ = _get_openai_config()
    if openai_key:
        result = call_openai_agent(user_message, current_answers, recent_messages, contact_info, is_followup=is_followup, schedule_url=schedule_url)
        if result:
            return result

    return None


_MONEY_PATTERN = re.compile(
    r"(\b\d+(\.\d+)?\s*(lakh|lac|cr|crore|k|thousand|rupee|rs|inr|₹)\b|\/mo|\bper month\b|\brent\b|\bdeposit\b)",
    re.IGNORECASE,
)
_TIMEFRAME_PATTERN = re.compile(
    r"\b(immediate|urgent|soon|day|week|month|year|explore|exploring|research|ready|now)\b",
    re.IGNORECASE,
)
_OPTION_REQUEST_PATTERN = re.compile(
    r"\b(option|options|choice|choices|kya option|show options|list options|give options|provide option|provide options|options batao)\b",
    re.IGNORECASE,
)
_SCHEDULING_PATTERN = re.compile(
    r"\b(schedule|meeting|calendly|consultation|appointment|book slot|book a slot|call slot|"
    r"talk to agent|speak with agent|site visit|site visit slot|site visit schedule|timing|"
    r"time slot|morning slot|afternoon slot|evening slot|morning|afternoon|evening|weekend visit|slot)\b",
    re.IGNORECASE,
)
_INAPPROPRIATE_PATTERN = re.compile(
    r"\b("
    r"fuck|fucking|fucker|shit|bitch|bastard|asshole|dick|cock|pussy|porn|nude|sex|sexy|horny|"
    r"idiot|stupid|dumb|shut\s*up|kill\s*yourself|useless|scam|fraud|cheat|loot|chor|"
    r"chutiya|chutiye|madarchod|bhosdike|bhosadi|gaand|gandu|harami|kameena|saale|saala|kutta|kutte|"
    r"bewakoof|pagal|bakwas|bakwaas|lund|lauda|randi|terimak|bc|mc"
    r")\b",
    re.IGNORECASE,
)
_GIBBERISH_PATTERN = re.compile(
    r"(\b(asdf|qwerty|zxcv|hjkl|dfgh)\w*\b|([a-zA-Z])\3{4,}|\b[bcdfghjklmnpqrstvwxyz]{5,}\b)",
    re.IGNORECASE,
)


def is_inappropriate_message(text: str) -> bool:
    """Detect offensive words, abusive language, insults, or random keyboard smash."""
    if not text:
        return False
    return bool(_INAPPROPRIATE_PATTERN.search(text) or _GIBBERISH_PATTERN.search(text))


def get_inappropriate_message_redirection(answers: dict, lang: str = "en") -> str:
    """Return a polite, professional boundary that immediately steers conversation back to property enquiry in English, Hindi, or Hinglish."""
    pending_slot = next((s for s in ORDERED_REQUIRED_SLOTS if not answers.get(s)), "location_preference")
    prompts = QUESTION_PROMPTS_MULTILINGUAL.get(lang, QUESTION_PROMPTS_MULTILINGUAL["en"])
    prefix = prompts.get("inappropriate", QUESTION_PROMPTS_MULTILINGUAL["en"]["inappropriate"])
    q_text = get_question_prompt(pending_slot, lang=lang)
    return prefix + q_text


def _sanitize_and_validate_turn(
    extracted: dict,
    answers: dict,
    user_message: str,
    llm_reply: str,
    llm_complete: bool,
    was_already_complete: bool = False,
    recent_messages: list | None = None,
) -> tuple[dict, str, bool]:
    """Sanitize extracted slots, enforce numbered options and 1-question-at-a-time flow."""
    # 0. Track and persist language
    current_lang = answers.get("language", "en")
    lang = detect_language(user_message, current_lang=current_lang)
    answers["language"] = lang

    # Strip repetitive greetings on subsequent turns
    has_prior_history = bool(recent_messages and len(recent_messages) > 1)
    if has_prior_history or was_already_complete:
        llm_reply = _strip_repetitive_greetings(llm_reply)

    if was_already_complete:
        return answers, llm_reply, False

    # 1. Determine which required question was pending before this message
    pending_slot = None
    for s in ORDERED_REQUIRED_SLOTS:
        if not answers.get(s):
            pending_slot = s
            break
    if not pending_slot and not answers.get("remarks_requirements"):
        pending_slot = "remarks_requirements"

    # 2. Check if customer asked to speak to a person
    if _SPEAK_TO_HUMAN_PATTERN.search(user_message):
        if not answers.get("remarks_requirements"):
            answers["remarks_requirements"] = "Customer requested to speak with a sales executive"
        missing_core = [s for s in ORDERED_REQUIRED_SLOTS if not answers.get(s)]
        if not missing_core:
            return answers, "", True
        next_slot = missing_core[0]
        reassurance = {
            "hi": "हमारे सेल्स एग्जीक्यूटिव जल्द ही आपको कॉल करेंगे। वे आपके लिए सही प्रॉपर्टी ला सकें, इसके लिए कृपया बताएं:\n\n",
            "hinglish": "Hamare sales executive jald hi aapko call karenge. Woh aapke hisab se best options laa sakein, iske liye please batayein:\n\n",
            "en": "Our sales executive will connect with you shortly! To help them prepare the best options for you, please let us know:\n\n",
        }.get(lang, "Our sales executive will connect with you shortly! To help them prepare the best options for you, please let us know:\n\n")
        return answers, f"{reassurance}{get_question_prompt(next_slot, lang=lang)}", False

    # 3. Handle numbered choice resolution (1, 2, 3...) or "skip" for pending slot
    if pending_slot:
        choice = _resolve_numbered_choice(user_message, pending_slot)
        if choice:
            answers[pending_slot] = choice
        elif user_message.strip().lower() in {"skip", "chhod do", "aage badho", "aage bado"}:
            if pending_slot == "remarks_requirements":
                answers["remarks_requirements"] = answers.get("form_requirement") or "None"
            else:
                # Required field skipped! Rule: "Required fields must be answered before you move on. If the customer skips one, politely ask again."
                prompts = QUESTION_PROMPTS_MULTILINGUAL.get(lang, QUESTION_PROMPTS_MULTILINGUAL["en"])
                skip_warn = prompts.get("skip_warning", "Please answer this question before we move on:\n\n")
                return answers, f"{skip_warn}{get_question_prompt(pending_slot, lang=lang)}", False
        elif pending_slot == "remarks_requirements":
            if answers.get("form_requirement") and answers["form_requirement"] not in user_message:
                answers["remarks_requirements"] = f"{answers['form_requirement']}. {user_message.strip()}"
            else:
                answers["remarks_requirements"] = user_message.strip()

    # 4. Merge extracted slots from LLM
    for key, val in (extracted or {}).items():
        if not val or not str(val).strip():
            continue
        clean_val = str(val).strip()
        if clean_val.lower() in {"not specified", "none", "unknown", "n/a", "null"}:
            continue
        if not answers.get(key):
            answers[key] = clean_val

    # 5. Contextual extraction from user message
    msg_lower = user_message.lower()
    if not answers.get("bhk_preference"):
        if any(w in msg_lower for w in ["1 bhk", "1bhk", "1 बीएचके"]):
            answers["bhk_preference"] = "1 BHK"
        elif any(w in msg_lower for w in ["2 bhk", "2bhk", "2 बीएचके"]):
            answers["bhk_preference"] = "2 BHK"
        elif any(w in msg_lower for w in ["3 bhk", "3bhk", "3 बीएचके"]):
            answers["bhk_preference"] = "3 BHK"
        elif any(w in msg_lower for w in ["4 bhk", "4bhk", "5 bhk", "4+ bhk", "4 बीएचके"]):
            answers["bhk_preference"] = "4 BHK or more"
        elif any(w in msg_lower for w in ["house", "villa", "kothi", "bungalow", "ghar", "makan", "मकान", "घर"]):
            answers["bhk_preference"] = "3 BHK"
        elif any(w in msg_lower for w in ["plot", "land", "zameen", "ज़मीन", "प्लॉट"]):
            answers["bhk_preference"] = "Residential Plot / Land"
        elif any(w in msg_lower for w in ["commercial", "shop", "dukan", "office", "retail", "showroom", "दुकान"]):
            answers["bhk_preference"] = "Commercial Space / Retail Shop"

    if not answers.get("location_preference"):
        for loc_cand in ["dwarka", "haldwani", "rampur road", "kaladhungi", "bithoria", "mukhani", "nainital", "bhimtal", "almora"]:
            if loc_cand in msg_lower:
                answers["location_preference"] = loc_cand.title()
                break
        if not answers.get("location_preference"):
            if "हल्द्वानी" in user_message:
                answers["location_preference"] = "Haldwani"
            elif "नैनीताल" in user_message or "भीमताल" in user_message:
                answers["location_preference"] = "Nainital / Bhimtal"
            elif "अल्मोड़ा" in user_message or "अल्मोडा" in user_message:
                answers["location_preference"] = "Almora"

    if not answers.get("budget_range") and (_MONEY_PATTERN.search(user_message) or any(w in user_message for w in ["लाख", "करोड़"])):
        answers["budget_range"] = user_message.strip()

    if not answers.get("payment_option"):
        if any(w in msg_lower for w in ["full payment", "cash", "self fund", "poora cash", "नकद", "पूरा भुगतान"]):
            answers["payment_option"] = "Full payment"
        elif any(w in msg_lower for w in ["home loan", "bank loan", "finance", "emi", "loan", "लोन"]):
            answers["payment_option"] = "Home loan"
        elif any(w in msg_lower for w in ["combination", "savings and loan", "part cash", "दोनों"]):
            answers["payment_option"] = "Combination of savings and loan"

    if not answers.get("planning_to_buy"):
        if any(w in msg_lower for w in ["immediate", "urgent", "ready", "1 month", "one month", "jaldi", "जल्दी", "1 महीने"]):
            answers["planning_to_buy"] = "Within 1 month"
        elif any(w in msg_lower for w in ["1 to 3", "2 months", "3 months", "3 महीने"]):
            answers["planning_to_buy"] = "1 to 3 months"
        elif any(w in msg_lower for w in ["3 to 6", "6 months", "6 महीने"]):
            answers["planning_to_buy"] = "3 to 6 months"
        elif any(w in msg_lower for w in ["exploring", "research", "dekh rahe", "देख रहे"]):
            answers["planning_to_buy"] = "Just exploring"

    # 6. Check what is missing now (in order)
    missing_required = [s for s in ORDERED_REQUIRED_SLOTS if not answers.get(s)]
    if missing_required:
        next_slot = missing_required[0]
        return answers, get_question_prompt(next_slot, lang=lang), False
    elif not answers.get("remarks_requirements"):
        return answers, get_question_prompt("remarks_requirements", lang=lang), False
    else:
        # All 6 questions answered!
        return answers, "", True


def execute_hybrid_ai_turn(
    conversation: dict,
    user_message: str,
    phone: str,
    schedule_url: str,
) -> dict | None:
    """Run an AI turn, merge newly extracted slots, and return the reply and completion state."""
    answers = dict(conversation.get("answers", {}))
    messages = list(conversation.get("messages", []))
    current_lang = answers.get("language", "en")
    lang = detect_language(user_message, current_lang=current_lang)
    answers["language"] = lang
    had_all_core_slots_before = all(
        bool(answers.get(k))
        for k in ["location_preference", "planning_to_buy", "budget_range", "payment_option", "bhk_preference"]
    )
    was_already_complete = (
        had_all_core_slots_before
        and (
            conversation.get("status") == "complete"
            or conversation.get("stage") == "complete"
            or bool(conversation.get("completed_at"))
            or conversation.get("source") == "property_enquiry_form"
        )
    )
    contact_info = {
        "full_name": answers.get("full_name") or conversation.get("full_name", ""),
        "first_name": answers.get("first_name", ""),
        "email": answers.get("email", ""),
        "phone": phone,
    }

    cal_url = build_prefilled_calendly_url(schedule_url, {**answers, "phone": phone})

    # Direct handler if customer sends an inappropriate or abusive message: steer back to property enquiry
    if is_inappropriate_message(user_message):
        redirect_reply = get_inappropriate_message_redirection(answers, lang=lang)
        now_iso = datetime.now(timezone.utc).isoformat()
        return {
            "reply_text": redirect_reply,
            "updated_answers": answers,
            "updated_messages": messages + [
                {"role": "user", "content": user_message, "timestamp": now_iso},
                {"role": "assistant", "content": redirect_reply, "timestamp": now_iso},
            ],
            "is_complete": False,
            "is_followup": was_already_complete,
        }

    # Direct handler if customer specifically asks to schedule meeting / consultation / Calendly
    if _SCHEDULING_PATTERN.search(user_message):
        schedule_reply = (
            "📅 *Schedule a 1-on-1 Consultation / Site Visit:*\n\n"
            "You can choose a date and convenient time slot that works best for you here:\n"
            f"👉 {cal_url}\n\n"
            "Your contact details are pre-filled so you can select your slot in one click. "
            "Our property specialist will be prepared with tailored recommendations for your meeting!"
        )
        now_iso = datetime.now(timezone.utc).isoformat()
        return {
            "reply_text": schedule_reply,
            "updated_answers": answers,
            "updated_messages": messages + [
                {"role": "user", "content": user_message, "timestamp": now_iso},
                {"role": "assistant", "content": schedule_reply, "timestamp": now_iso},
            ],
            "is_complete": False,
            "is_followup": was_already_complete,
        }

    ai_result = call_ai_agent(user_message, answers, messages, contact_info, is_followup=was_already_complete, schedule_url=cal_url)
    if not ai_result:
        first_name = answers.get("first_name") or "there"
        msg_l = user_message.lower()
        raw_extracted = {}
        if any(w in msg_l for w in ["job", "work", "naukri", "office", "interview", "haldwani"]):
            raw_reply = (
                "Congratulations on your job opportunity in Haldwani! 🌟\n\n"
                "Having a comfortable home close to your workplace makes daily commute so much easier. "
                "Here are great living options near commercial & office corridors in Haldwani:\n\n"
                "• 1 BHK Rental Apartment (₹6,000 - ₹12,000 / mo)\n"
                "• 2 BHK Family Rental Flat (₹12,000 - ₹20,000 / mo)\n"
                "• Independent House / Villa for Rent or Purchase\n"
                "• Residential Plot to build your own dream home\n\n"
                "Which area is your workplace located in, and which option works best for you?"
            )
            raw_complete = False
        elif any(w in msg_l for w in ["business", "shop", "dukan", "commercial", "startup", "cafe", "restaurant", "clinic"]):
            raw_reply = (
                "Wishing you immense success with your commercial venture! 🚀\n\n"
                "Prime location and footfall are key for high growth. Here are top commercial property options in Haldwani:\n\n"
                "• High-Street Retail Shop on Main Corridor\n"
                "• Modern Commercial Office Space in Business Hub\n"
                "• Highway Commercial Plot / Showroom Space\n\n"
                "Which configuration and budget do you prefer to explore?"
            )
            raw_complete = False
        elif any(w in msg_l for w in ["school", "college", "children", "kids", "admission", "tuition"]):
            raw_reply = (
                "Living near top schools saves precious travel time for your family every day. 📚\n\n"
                "Here are premier residential options in safe, family-friendly neighborhoods:\n\n"
                "• 2 BHK / 3 BHK Gated Society Apartment\n"
                "• Independent 3+ BHK Family Villa with Private Garden\n"
                "• Residential Plots in Premium Localities\n\n"
                "Which of these options would you prefer for your family?"
            )
            raw_complete = False
        elif any(w in msg_l for w in ["weather", "mausam", "tourism", "visit", "trip", "nainital", "bhimtal", "holiday", "peace"]):
            raw_reply = (
                "The foothills offer scenic Himalayan views and refreshing weather all year round. 🌄\n\n"
                "Here are popular peaceful getaway properties and holiday options:\n\n"
                "• Scenic Mountain-View Residential Plots in Bhimtal / Nainital\n"
                "• Luxury Holiday Villas in Peaceful Foothill Localities\n"
                "• Modern 2 BHK / 3 BHK Apartments with Beautiful Valley Views\n\n"
                "Are you considering a holiday retreat, retirement home, or an investment plot in the hills?"
            )
            raw_complete = False
        elif any(w in msg_l for w in ["house", "villa", "makan", "ghar"]):
            raw_extracted["bhk_preference"] = "Independent House / Villa"
            raw_reply = (
                "I've noted down your preference for an Independent House / Villa in Haldwani / Uttarakhand. 🏡\n\n"
                "Here are popular areas with premium independent villas:\n\n"
                "• Rampur Road (Prime connectivity & markets)\n"
                "• Kaladhungi Road (Peaceful residential hub)\n"
                "• Bithoria / Mukhani (Premium family locality)\n"
                "• Bhimtal / Nainital Road (Scenic foothill environment)\n\n"
                "Which area or budget range would you like us to shortlist for you?"
            )
            raw_complete = False
        elif _SCHEDULING_PATTERN.search(user_message):
            raw_reply = (
                "📅 *Schedule a 1-on-1 Consultation / Site Visit:*\n\n"
                "You can choose a date and convenient time slot here:\n"
                f"👉 {cal_url}\n\n"
                "Your details are pre-filled so you just need to pick your time slot!"
            )
            raw_complete = False
        elif any(w in msg_l for w in ["option", "options", "suggest", "choice", "help", "de do", "bataye"]):
            first_missing = next(
                (k for k in ["bhk_preference", "budget_range", "planning_to_buy", "payment_option"] if not answers.get(k)),
                "bhk_preference"
            )
            option_texts = {
                "bhk_preference": "Here are our available property configurations:\n• 1 BHK Apartment\n• 2 BHK Apartment\n• 3 BHK Apartment\n• 4+ BHK Luxury Villa\n• Residential Plot / Land\n• Commercial Office / Retail Shop",
                "budget_range": "Here are standard budget ranges:\n• Up to 25 Lakh\n• 25 - 50 Lakh\n• 50 Lakh - 1 Crore\n• 1 - 2 Crore\n• Above 2 Crore\n(Or for rentals: • ₹5,000 - ₹15,000 / mo • ₹15,000 - ₹30,000 / mo)",
                "planning_to_buy": "When are you planning to finalize?\n• Immediately\n• Within 1 Month\n• Within 3 Months\n• Within 6 Months\n• Just Exploring",
                "payment_option": "What is your preferred payment structure?\n• Bank Finance / Home Loan with EMI\n• Full Cash Payment / Self Funding\n• Flexible Down Payment Plan\n• Standard Rental Agreement",
            }
            raw_reply = "Here are the available options:\n\n" + option_texts.get(first_missing, option_texts["bhk_preference"])
            raw_complete = False
        elif was_already_complete:
            raw_reply = (
                "Understood. 🏡 Here are popular property choices currently available in Haldwani & Uttarakhand:\n\n"
                "• 1 BHK / 2 BHK / 3 BHK Apartments\n"
                "• Luxury Independent Villas\n"
                "• Gated Residential Plots\n"
                "• Commercial Showrooms & Offices\n\n"
                "Which of these would you like to explore?"
            )
            raw_complete = False
        else:
            raw_reply = (
                "Here are the available property options in Haldwani & Uttarakhand:\n\n"
                "• 1 BHK / 2 BHK Modern Apartment\n"
                "• 3 BHK / 4 BHK Luxury Villa\n"
                "• Residential Plot / Land\n"
                "• Commercial Office / Retail Space\n\n"
                "Which configuration fits your requirement?"
            )
            raw_complete = False
    else:
        raw_extracted = ai_result.get("extracted_slots", {})
        raw_reply = ai_result.get("reply_message", "").strip()
        raw_complete = bool(ai_result.get("is_complete", False))

    answers, reply_to_send, is_complete = _sanitize_and_validate_turn(
        raw_extracted,
        answers,
        user_message,
        raw_reply,
        raw_complete,
        was_already_complete=was_already_complete,
        recent_messages=messages,
    )

    if is_complete and not was_already_complete:
        first_name = answers.get("first_name") or "there"
        spoke_person = bool(_SPEAK_TO_HUMAN_PATTERN.search(user_message))
        reply_to_send = format_completion_summary_message(
            {**answers, "phone": phone, "mobile_number": answers.get("mobile_number") or phone},
            first_name=first_name,
            schedule_url=schedule_url,
            spoke_to_person=spoke_person,
            lang=answers.get("language", lang),
        )
    elif was_already_complete or (had_all_core_slots_before and bool(answers.get("remarks_requirements"))):
        # In last message / follow-up turns, always include the pre-filled Calendly link to schedule meeting
        if "calendly.com" not in reply_to_send:
            cal_block = _get_calendly_schedule_block(cal_url, lang=answers.get("language", lang))
            reply_to_send = f"{reply_to_send.rstrip()}\n\n{cal_block}"

    # Update message history
    now_iso = datetime.now(timezone.utc).isoformat()
    updated_messages = messages + [
        {"role": "user", "content": user_message, "timestamp": now_iso},
        {"role": "assistant", "content": reply_to_send, "timestamp": now_iso},
    ]

    return {
        "reply_text": reply_to_send,
        "updated_answers": answers,
        "updated_messages": updated_messages,
        "is_complete": is_complete and not was_already_complete,
        "is_followup": was_already_complete,
    }


def analyze_lead_with_ai(lead_data: dict, recent_messages: list | None = None) -> dict:
    """Use AI (Gemini / OpenAI) to analyze completed WhatsApp questionnaire data and qualify as Hot, Warm, or Cold.
    
    If AI classification succeeds:
    - Returns structured AI analysis with rating ('Hot', 'Warm', or 'Cold'), score (0-100), is_hot (bool), summary, and triggers.
    If AI is unavailable or fails:
    - Smoothly falls back to rule-based qualification engine from zoho_crm.evaluate_lead_quality.
    """
    from zoho_crm import evaluate_lead_quality

    lead_summary = {
        "customer_name": lead_data.get("full_name") or f"{lead_data.get('first_name', '')} {lead_data.get('last_name', '')}".strip() or "Customer",
        "phone": lead_data.get("mobile_number") or lead_data.get("contact_number") or "",
        "location": lead_data.get("location_preference") or "",
        "configuration": lead_data.get("bhk_preference") or "",
        "budget": lead_data.get("budget_range") or "",
        "timeline": lead_data.get("planning_to_buy") or "",
        "payment": lead_data.get("payment_option") or "",
        "requirements": lead_data.get("remarks_requirements") or lead_data.get("requirement") or "",
    }

    conv_context = []
    if recent_messages:
        for m in recent_messages[-4:]:
            conv_context.append(f"{m.get('role', 'user').capitalize()}: {m.get('content', '')}")
    if conv_context:
        lead_summary["recent_chat"] = conv_context

    system_prompt = (
        "You are an expert Real Estate Lead Qualification Specialist for Profilent CRM.\n"
        "Analyze the customer's completed property enquiry to classify their buying urgency and lead quality.\n\n"
        "Classification Rules:\n"
        "1. HOT LEAD (Score: 60 - 100, is_hot: true):\n"
        "   - Urgent buying/renting timeline: 'Immediately' or 'Within 1 Month'\n"
        "   - High budget: ₹1 Crore+, ₹2 Crore+, or premium property\n"
        "   - Full cash payment, pre-approved finance, or urgent relocation requirement\n"
        "   - Direct consultation booking or request for immediate site visit\n\n"
        "2. WARM LEAD (Score: 30 - 59, is_hot: false):\n"
        "   - Medium timeline: 'Within 3 Months' or 'Within 6 Months'\n"
        "   - Standard budget with planned bank home loan / EMI\n"
        "   - Clear requirements but not looking to finalize within 30 days\n\n"
        "3. COLD LEAD (Score: 0 - 29, is_hot: false):\n"
        "   - Distant timeline: 'Within 12 Months', 'More Than 1 Year', or 'Just Exploring / Researching'\n"
        "   - Casual browsing or vague/non-committal intent\n\n"
        "Respond ONLY with valid JSON:\n"
        "{\n"
        '  "rating": "Hot" | "Warm" | "Cold",\n'
        '  "score": <integer 0-100>,\n'
        '  "is_hot": <boolean: true if Hot else false>,\n'
        '  "summary": "<1-2 sentence executive assessment of lead urgency and intent>",\n'
        '  "triggers": ["<list of 1-3 key qualification trigger points>"]\n'
        "}"
    )

    # 1. Try Gemini
    gemini_key, gemini_model = _get_gemini_config()
    if gemini_key:
        models_to_try = [gemini_model]
        for alt in ["gemini-3.5-flash-lite", "gemini-3.5-flash", "gemma-4-26b-a4b-it"]:
            if alt not in models_to_try:
                models_to_try.append(alt)

        payload = {
            "systemInstruction": {"parts": [{"text": system_prompt}]},
            "contents": [{"role": "user", "parts": [{"text": f"Customer lead details:\n{json.dumps(lead_summary, indent=2)}"}]}],
            "generationConfig": {
                "responseMimeType": "application/json",
                "temperature": 0.2,
                "maxOutputTokens": 400,
            },
        }

        for current_model in models_to_try:
            try:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{current_model}:generateContent?key={gemini_key}"
                resp = _ai_session.post(url, headers={"Content-Type": "application/json"}, json=payload, timeout=10)
                if not resp.ok:
                    continue
                body = resp.json()
                raw_text = body.get("candidates", [])[0].get("content", {}).get("parts", [{}])[0].get("text", "").strip()
                parsed = _extract_json_object(raw_text)
                if not parsed:
                    continue
                rating = parsed.get("rating", "Warm").capitalize()
                if rating not in ("Hot", "Warm", "Cold"):
                    rating = "Hot" if parsed.get("is_hot") else "Warm"
                is_hot = (rating == "Hot")
                score = int(parsed.get("score") or (80 if is_hot else (45 if rating == "Warm" else 15)))
                return {
                    "rating": rating,
                    "score": score,
                    "is_hot": is_hot,
                    "summary": str(parsed.get("summary") or f"AI evaluated as {rating} lead"),
                    "triggers": parsed.get("triggers") or [f"AI classified {rating}"],
                    "ai_qualified": True,
                }
            except Exception as e:
                logger.warning("Gemini model %s AI lead analysis failed: %s", current_model, e)
                continue

    # 2. Try OpenAI
    openai_key, openai_model = _get_openai_config()
    if openai_key:
        try:
            payload = {
                "model": openai_model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"Customer lead details:\n{json.dumps(lead_summary, indent=2)}"},
                ],
                "response_format": {"type": "json_object"},
                "temperature": 0.2,
                "max_tokens": 400,
            }
            resp = _ai_session.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {openai_key}", "Content-Type": "application/json"},
                json=payload,
                timeout=10,
            )
            if resp.ok:
                body = resp.json()
                raw_text = body.get("choices", [])[0].get("message", {}).get("content", "").strip()
                parsed = json.loads(raw_text)
                rating = parsed.get("rating", "Warm").capitalize()
                if rating not in ("Hot", "Warm", "Cold"):
                    rating = "Hot" if parsed.get("is_hot") else "Warm"
                is_hot = (rating == "Hot")
                score = int(parsed.get("score") or (80 if is_hot else (45 if rating == "Warm" else 15)))
                return {
                    "rating": rating,
                    "score": score,
                    "is_hot": is_hot,
                    "summary": str(parsed.get("summary") or f"AI evaluated as {rating} lead"),
                    "triggers": parsed.get("triggers") or [f"AI classified {rating}"],
                    "ai_qualified": True,
                }
        except Exception as e:
            logger.warning("OpenAI lead analysis failed (%s); falling back to rule-based qualification.", e)

    # 3. Fallback to rule-based qualification
    base_eval = evaluate_lead_quality(lead_data)
    return {
        "rating": base_eval["rating"],
        "score": base_eval["score"],
        "is_hot": base_eval["is_hot"],
        "summary": ", ".join(base_eval["reasons"]) or f"Evaluated as {base_eval['rating']} lead",
        "triggers": base_eval["triggers"],
        "ai_qualified": False,
    }
