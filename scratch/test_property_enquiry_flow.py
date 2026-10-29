import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from conversation_ai import analyze_lead_with_ai
from whatsapp_bot import format_completion_summary_message, build_prefilled_calendly_url
from zoho_crm import evaluate_lead_quality

# 1. Test HOT Lead analysis (Urgent timeline + High budget + Home loan)
hot_lead = {
    "first_name": "Rahul",
    "last_name": "Sharma",
    "full_name": "Rahul Sharma",
    "email": "rahul.sharma@example.com",
    "mobile_number": "+919876543210",
    "location_preference": "Haldwani (Rampur Rd)",
    "planning_to_buy": "Within 1 month",
    "budget_range": "₹80 lakh to ₹1 crore",
    "payment_option": "Full payment",
    "bhk_preference": "3 BHK",
    "remarks_requirements": "Near main road with 2 car parking",
}

eval_hot = analyze_lead_with_ai(hot_lead)
print("Hot lead evaluation:", eval_hot["rating"], f"(Score: {eval_hot['score']})")
assert eval_hot["rating"] == "Hot", "Expected Hot lead"
assert eval_hot["is_hot"] is True, "Expected is_hot to be True"

# 2. Test COLD Lead analysis (Just exploring + low budget)
cold_lead = {
    "first_name": "Vikas",
    "last_name": "Verma",
    "full_name": "Vikas Verma",
    "email": "vikas.verma@example.com",
    "mobile_number": "+919876543211",
    "location_preference": "Almora",
    "planning_to_buy": "Just exploring",
    "budget_range": "Below ₹30 lakh",
    "payment_option": "Not decided yet",
    "bhk_preference": "1 BHK",
    "remarks_requirements": "None",
}

eval_cold = analyze_lead_with_ai(cold_lead)
print("Cold lead evaluation:", eval_cold["rating"], f"(Score: {eval_cold['score']})")
assert eval_cold["rating"] == "Cold", "Expected Cold lead"
assert eval_cold["is_hot"] is False, "Expected is_hot to be False"

# 3. Test WhatsApp summary message with pre-filled Calendly link
msg = format_completion_summary_message(hot_lead, first_name="Rahul", schedule_url="https://calendly.com/shailendra-profilent/30min")
print("\nGenerated WhatsApp Message for Property Form: [OK]")

assert "Rahul" in msg
assert "Haldwani" in msg
assert "Within 1 month" in msg
assert "Full payment" in msg
assert "3 BHK" in msg
assert "calendly.com" in msg
assert "name=Rahul" in msg

print("ALL PROPERTY ENQUIRY FLOW TESTS PASSED!")
