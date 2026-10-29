import sys
import os
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from conversation_ai import execute_hybrid_ai_turn, is_inappropriate_message, get_inappropriate_message_redirection

print("=== TEST 1: Check Inappropriate Message Detection ===")
sample_abuses = [
    "you are idiot",
    "shut up",
    "bakwas service",
    "fuck this",
    "pagal bot",
    "asdfghjkl",
]

for msg in sample_abuses:
    assert is_inappropriate_message(msg), f"Failed to detect abuse: {msg}"
print("All abuse samples correctly detected!")

print("\n=== TEST 2: Turn Execution on Inappropriate Message ===")
conv = {
    "_id": "test_conv_inappropriate",
    "status": "in_progress",
    "stage": "q_ai_flow",
    "answers": {
        "first_name": "Shailendra",
    },
    "messages": [
        {"role": "assistant", "content": "Welcome! Which location in Uttarakhand are you interested in?"}
    ]
}

res = execute_hybrid_ai_turn(conv, "you are so stupid and bakwas", phone="+919068978137", schedule_url=None)
print("Reply text:\n" + res["reply_text"])
assert "exclusively with finding the best properties" in res["reply_text"]
assert "Let's focus on your property search!" in res["reply_text"]
assert "1. Haldwani" in res["reply_text"]
assert res["is_complete"] is False
print("Steer-back to property search succeeded!")

print("\n=== TEST 3: Normal Property Messages Are NOT Flagged ===")
normal_messages = [
    "I need 3 BHK in Haldwani",
    "my budget is 50 lakh",
    "commercial retail shop",
    "whatsapp chat only",
    "afternoon",
]
for msg in normal_messages:
    assert not is_inappropriate_message(msg), f"Normal message falsely flagged: {msg}"
print("Normal property messages confirmed unaffected!")

print("\nALL INAPPROPRIATE REDIRECTION TESTS PASSED!")
