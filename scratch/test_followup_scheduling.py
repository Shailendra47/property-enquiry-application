import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from conversation_ai import execute_hybrid_ai_turn

# Test follow-up where customer already completed questionnaire
conv = {
    "status": "complete",
    "stage": "complete",
    "answers": {
        "full_name": "Shailendra deo",
        "first_name": "Shailendra",
        "location_preference": "Haldwani",
        "planning_to_buy": "Within 1 month",
        "budget_range": "₹50 lakh to ₹80 lakh",
        "payment_option": "Home loan",
        "bhk_preference": "2 BHK",
        "remarks_requirements": "None",
    },
    "messages": [
        {"role": "user", "content": "Hi"},
        {"role": "assistant", "content": "Schedule a meeting with Profilent: https://calendly.com/shailendra-profilent/30min"},
    ],
}

# Turn: customer asks for afternoon slot or site visit
turn1 = execute_hybrid_ai_turn(conv, "afternoon", "+919876543210", "https://calendly.com/shailendra-profilent/30min")
print("Response to 'afternoon': [contains Calendly URL]")
assert "calendly.com" in turn1["reply_text"], "Must contain Calendly link"
assert "Sector 7" not in turn1["reply_text"], "Must NOT hallucinate Sector 7"

turn2 = execute_hybrid_ai_turn(conv, "can we do a site visit?", "+919876543210", "https://calendly.com/shailendra-profilent/30min")
print("Response to 'site visit': [contains Calendly URL]")
assert "calendly.com" in turn2["reply_text"], "Must contain Calendly link"

print("\nALL FOLLOWUP SCHEDULING TESTS PASSED!")
