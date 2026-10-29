import sys
import os

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from conversation_ai import execute_hybrid_ai_turn
from whatsapp_bot import format_completion_summary_message

print("=== TEST 1: Full 6-Question Flow with Numbers & Skip ===")

conv = {
    "_id": "test_profilent_flow",
    "status": "in_progress",
    "stage": "q_ai_flow",
    "answers": {
        "first_name": "Shailendra",
    },
    "messages": []
}

# Turn 1: Reply to initial message with "1" (Haldwani)
res1 = execute_hybrid_ai_turn(conv, "1", phone="+919068978137", schedule_url=None)
print("After Turn 1, Reply:")
print(res1["reply_text"])
assert "What is your timeline?" in res1["reply_text"]
assert res1["updated_answers"]["location_preference"].startswith("Haldwani")
assert res1["is_complete"] is False

# Turn 2: Reply with "2" (1 to 3 months)
conv["answers"] = res1["updated_answers"]
conv["messages"] = res1["updated_messages"]
res2 = execute_hybrid_ai_turn(conv, "2", phone="+919068978137", schedule_url=None)
print("\nAfter Turn 2, Reply:")
print(res2["reply_text"])
assert "What is your budget?" in res2["reply_text"]
assert res2["updated_answers"]["planning_to_buy"] == "1 to 3 months"
assert res2["is_complete"] is False

# Turn 3: Reply with "2" (₹30 lakh to ₹50 lakh)
conv["answers"] = res2["updated_answers"]
conv["messages"] = res2["updated_messages"]
res3 = execute_hybrid_ai_turn(conv, "2", phone="+919068978137", schedule_url=None)
print("\nAfter Turn 3, Reply:")
print(res3["reply_text"])
assert "How do you plan to pay?" in res3["reply_text"]
assert res3["updated_answers"]["budget_range"] == "₹30 lakh to ₹50 lakh"
assert res3["is_complete"] is False

# Turn 4: Reply with "2" (Home loan)
conv["answers"] = res3["updated_answers"]
conv["messages"] = res3["updated_messages"]
res4 = execute_hybrid_ai_turn(conv, "2", phone="+919068978137", schedule_url=None)
print("\nAfter Turn 4, Reply:")
print(res4["reply_text"])
assert "Which configuration do you need?" in res4["reply_text"]
assert res4["updated_answers"]["payment_option"] == "Home loan"
assert res4["is_complete"] is False

# Turn 5: Reply with "2" (2 BHK)
conv["answers"] = res4["updated_answers"]
conv["messages"] = res4["updated_messages"]
res5 = execute_hybrid_ai_turn(conv, "2", phone="+919068978137", schedule_url=None)
print("\nAfter Turn 5, Reply:")
print(res5["reply_text"])
assert "Do you have any other requirements" in res5["reply_text"]
assert res5["updated_answers"]["bhk_preference"] == "2 BHK"
assert res5["is_complete"] is False

# Turn 6: Reply with "skip"
conv["answers"] = res5["updated_answers"]
conv["messages"] = res5["updated_messages"]
res6 = execute_hybrid_ai_turn(conv, "skip", phone="+919068978137", schedule_url=None)
print("\nAfter Turn 6 (Final Summary):")
print(res6["reply_text"])
assert res6["is_complete"] is True
assert "Thank you, Shailendra! I've noted down all your requirements:" in res6["reply_text"]
assert "• Location: Haldwani" in res6["reply_text"]
assert "• Configuration: 2 BHK" in res6["reply_text"]
assert "• Budget: ₹30 lakh to ₹50 lakh" in res6["reply_text"]
assert "• Timeline: 1 to 3 months" in res6["reply_text"]
assert "• Payment Option: Home loan" in res6["reply_text"]
assert "• Special Requirements: None" in res6["reply_text"]
assert "Our property specialist team will review your preferences and share hand-picked options." in res6["reply_text"]
assert "Schedule a 1-on-1 consultation at your convenience:" in res6["reply_text"]
assert "https://calendly.com/" in res6["reply_text"]

print("\n=== TEST 2: Required Field Skip Prevention ===")
conv_skip_test = {
    "_id": "test_skip",
    "status": "in_progress",
    "stage": "q_ai_flow",
    "answers": {"first_name": "Test"},
    "messages": []
}
# User tries to skip required question 1 (Location)
res_skip = execute_hybrid_ai_turn(conv_skip_test, "skip", phone="+919068978137", schedule_url=None)
print("Skip response on required field:")
print(res_skip["reply_text"])
assert "Please answer this question before we move on" in res_skip["reply_text"]
assert res_skip["is_complete"] is False

print("\n=== TEST 3: Speak to Human / Sales Executive ===")
conv_human_test = {
    "_id": "test_human",
    "status": "in_progress",
    "stage": "q_ai_flow",
    "answers": {
        "first_name": "Amit",
        "location_preference": "Nainital / Bhimtal",
    },
    "messages": []
}
res_human = execute_hybrid_ai_turn(conv_human_test, "I want to speak to a person", phone="+919068978137", schedule_url=None)
print("Speak to human response:")
print(res_human["reply_text"])
assert "sales executive will connect with you shortly" in res_human["reply_text"].lower()
assert "What is your timeline?" in res_human["reply_text"]
assert res_human["is_complete"] is False

print("\nALL PROFILENT SPECIFICATION TESTS PASSED WITH 100% ACCURACY!")

