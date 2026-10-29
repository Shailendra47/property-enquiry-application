import sys
import os

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from conversation_ai import (
    execute_hybrid_ai_turn,
    detect_language,
    get_question_prompt,
    get_inappropriate_message_redirection,
    QUESTION_PROMPTS_MULTILINGUAL,
)
from whatsapp_bot import format_completion_summary_message

print("=== 1. TESTING LANGUAGE DETECTION ===")
assert detect_language("Hello I need a house", "en") == "en"
assert detect_language("mujhe haldwani me property chahiye", "en") == "hinglish"
assert detect_language("नमस्ते मुझे हल्द्वानी में 2 बीएचके चाहिए", "en") == "hi"
assert detect_language("1", "hinglish") == "hinglish"
assert detect_language("२", "hi") == "hi"
print("✓ Language detection passed")

print("\n=== 2. TESTING INAPPROPRIATE REDIRECTION ACROSS LANGUAGES ===")
r_en = get_inappropriate_message_redirection({"location_preference": "Haldwani"}, lang="en")
assert "I am here to assist you exclusively" in r_en
assert "What is your timeline?" in r_en

r_hinglish = get_inappropriate_message_redirection({"location_preference": "Haldwani"}, lang="hinglish")
assert "Main yahan Haldwani aur Uttarakhand me best property" in r_hinglish
assert "Aapka timeline kya hai" in r_hinglish

r_hi = get_inappropriate_message_redirection({"location_preference": "Haldwani"}, lang="hi")
assert "मैं यहां हल्द्वानी और उत्तराखंड में बेहतरीन प्रॉपर्टी" in r_hi
assert "आपकी समयसीमा क्या है" in r_hi
print("✓ Inappropriate message redirection in all 3 languages passed")

print("\n=== 3. TESTING HINGLISH E2E QUESTIONNAIRE FLOW ===")
conv = {
    "phone": "+919876543210",
    "answers": {"first_name": "Rahul", "language": "hinglish"},
    "messages": [],
    "status": "in_progress",
}

# Turn 1: User says "Mujhe Haldwani me property dekhni hai"
t1 = execute_hybrid_ai_turn(conv, "Mujhe Haldwani me flat dekhna hai", "+919876543210", "https://calendly.com/profilent/30min")
assert t1["updated_answers"]["location_preference"] == "Haldwani"
assert t1["updated_answers"]["language"] == "hinglish"
assert "timeline kya hai" in t1["reply_text"].lower() or "1 month ke andar" in t1["reply_text"]
print("✓ Hinglish Turn 1 passed")

# Turn 2: User answers timeline "1"
conv["answers"] = t1["updated_answers"]
conv["messages"] = t1["updated_messages"]
t2 = execute_hybrid_ai_turn(conv, "1", "+919876543210", "https://calendly.com/profilent/30min")
assert t2["updated_answers"]["planning_to_buy"] == "Within 1 month"
assert "budget kitna hai" in t2["reply_text"].lower() or "30 lakh" in t2["reply_text"]
print("✓ Hinglish Turn 2 passed")

# Turn 3: User skips budget (required!) -> Should warn in Hinglish!
conv["answers"] = t2["updated_answers"]
conv["messages"] = t2["updated_messages"]
t3_skip = execute_hybrid_ai_turn(conv, "skip", "+919876543210", "https://calendly.com/profilent/30min")
assert "Aage badhne se pehle please is sawaal ka jawab dein" in t3_skip["reply_text"]
assert t3_skip["is_complete"] is False
print("✓ Hinglish Skip Prevention on required slot passed")

# Turn 3: User answers budget "2" (₹30 lakh to ₹50 lakh)
t3 = execute_hybrid_ai_turn(conv, "2", "+919876543210", "https://calendly.com/profilent/30min")
assert t3["updated_answers"]["budget_range"] == "₹30 lakh to ₹50 lakh"
assert "payment kaise plan" in t3["reply_text"].lower() or "home loan" in t3["reply_text"].lower()
print("✓ Hinglish Turn 3 passed")

# Turn 4: User answers payment "2" (Home loan)
conv["answers"] = t3["updated_answers"]
conv["messages"] = t3["updated_messages"]
t4 = execute_hybrid_ai_turn(conv, "2", "+919876543210", "https://calendly.com/profilent/30min")
assert t4["updated_answers"]["payment_option"] == "Home loan"
assert "kitne bhk" in t4["reply_text"].lower() or "2 bhk" in t4["reply_text"].lower()
print("✓ Hinglish Turn 4 passed")

# Turn 5: User answers BHK "2" (2 BHK)
conv["answers"] = t4["updated_answers"]
conv["messages"] = t4["updated_messages"]
t5 = execute_hybrid_ai_turn(conv, "2", "+919876543210", "https://calendly.com/profilent/30min")
assert t5["updated_answers"]["bhk_preference"] == "2 BHK"
assert "parking" in t5["reply_text"].lower() or "skip" in t5["reply_text"].lower()
print("✓ Hinglish Turn 5 passed")

# Turn 6: User skips remarks
conv["answers"] = t5["updated_answers"]
conv["messages"] = t5["updated_messages"]
t6 = execute_hybrid_ai_turn(conv, "skip", "+919876543210", "https://calendly.com/profilent/30min")
assert t6["is_complete"] is True
assert "Dhanyawaad, Rahul" in t6["reply_text"]
assert "Location: Haldwani" in t6["reply_text"]
assert "Budget: ₹30 lakh to ₹50 lakh" in t6["reply_text"]
assert "Hamari property specialist team" in t6["reply_text"]
assert "https://calendly.com/profilent/30min" in t6["reply_text"]
print("✓ Hinglish Turn 6 Completion Summary passed")

print("\n=== 4. TESTING HINDI (DEVANAGARI) E2E QUESTIONNAIRE FLOW ===")
conv_hi = {
    "phone": "+919876543210",
    "answers": {"first_name": "अमित", "language": "hi"},
    "messages": [],
    "status": "in_progress",
}

# Turn 1: User says in Devanagari Hindi
t1_hi = execute_hybrid_ai_turn(conv_hi, "नमस्ते मुझे हल्द्वानी में मकान चाहिए", "+919876543210", "https://calendly.com/profilent/30min")
assert t1_hi["updated_answers"]["location_preference"] == "Haldwani"
assert t1_hi["updated_answers"]["language"] == "hi"
assert "आपकी समयसीमा क्या है" in t1_hi["reply_text"]
print("✓ Hindi Turn 1 passed")

# Turn 2: User responds with Devanagari numeral "१" (Within 1 month)
conv_hi["answers"] = t1_hi["updated_answers"]
conv_hi["messages"] = t1_hi["updated_messages"]
t2_hi = execute_hybrid_ai_turn(conv_hi, "१", "+919876543210", "https://calendly.com/profilent/30min")
assert t2_hi["updated_answers"]["planning_to_buy"] == "Within 1 month"
assert "आपका बजट कितना है" in t2_hi["reply_text"]
print("✓ Hindi Turn 2 (with Devanagari numeral १) passed")

# Turn 3: User answers budget with "३" (₹50 lakh to ₹80 lakh)
conv_hi["answers"] = t2_hi["updated_answers"]
conv_hi["messages"] = t2_hi["updated_messages"]
t3_hi = execute_hybrid_ai_turn(conv_hi, "३", "+919876543210", "https://calendly.com/profilent/30min")
assert t3_hi["updated_answers"]["budget_range"] == "₹50 lakh to ₹80 lakh"
assert "भुगतान किस प्रकार" in t3_hi["reply_text"]
print("✓ Hindi Turn 3 (with Devanagari numeral ३) passed")

# Turn 4: User answers payment "२" (Home loan)
conv_hi["answers"] = t3_hi["updated_answers"]
conv_hi["messages"] = t3_hi["updated_messages"]
t4_hi = execute_hybrid_ai_turn(conv_hi, "२", "+919876543210", "https://calendly.com/profilent/30min")
assert t4_hi["updated_answers"]["payment_option"] == "Home loan"
# Because "मकान" was mentioned in Turn 1, bhk_preference was smartly pre-extracted!
# So the next pending question is Remarks/Requirements!
assert "पार्किंग" in t4_hi["reply_text"] or "skip" in t4_hi["reply_text"]
print("✓ Hindi Turn 4 (smart slot extraction skipped redundant BHK question to remarks) passed")

# Turn 5: User remarks in Hindi "ईस्ट फेसिंग और कार पार्किंग"
conv_hi["answers"] = t4_hi["updated_answers"]
conv_hi["messages"] = t4_hi["updated_messages"]
t5_hi = execute_hybrid_ai_turn(conv_hi, "ईस्ट फेसिंग और कार पार्किंग", "+919876543210", "https://calendly.com/profilent/30min")
assert t5_hi["is_complete"] is True
assert "धन्यवाद, अमित" in t5_hi["reply_text"]
assert "लोकेशन: Haldwani" in t5_hi["reply_text"]
assert "बजट: ₹50 lakh to ₹80 lakh" in t5_hi["reply_text"]
assert "विशेष आवश्यकताएं: ईस्ट फेसिंग और कार पार्किंग" in t5_hi["reply_text"]
assert "https://calendly.com/profilent/30min" in t5_hi["reply_text"]
print("✓ Hindi Turn 5 Completion Summary passed")

print("\n=== ALL MULTILINGUAL FLOW TESTS PASSED SUCCESSFULLY! ===")
