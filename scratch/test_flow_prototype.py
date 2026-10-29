import sys
import re

sys.stdout.reconfigure(encoding='utf-8')

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

QUESTION_PROMPTS = {
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
}

ORDERED_REQUIRED_SLOTS = [
    "location_preference",
    "planning_to_buy",
    "budget_range",
    "payment_option",
    "bhk_preference",
]

def resolve_choice(user_msg, slot):
    txt = user_msg.strip()
    m = re.match(r"^(?:option\s*|#\s*)?([1-5])[\.\)]?$", txt, re.IGNORECASE)
    if m:
        idx = int(m.group(1)) - 1
        opts = STANDARD_OPTIONS.get(slot, [])
        if 0 <= idx < len(opts):
            return opts[idx]
    return None

def process_turn(answers, user_msg):
    # Find pending slot
    pending = None
    for s in ORDERED_REQUIRED_SLOTS:
        if not answers.get(s):
            pending = s
            break
    if not pending and "remarks_requirements" not in answers:
        pending = "remarks_requirements"

    if pending:
        if user_msg.strip().lower() == "skip":
            if pending == "remarks_requirements":
                answers["remarks_requirements"] = "None"
            else:
                return answers, "This field is required. Please choose an option or share your preference:\n\n" + QUESTION_PROMPTS[pending], False
        else:
            choice = resolve_choice(user_msg, pending)
            if choice:
                answers[pending] = choice
            elif pending == "remarks_requirements":
                answers["remarks_requirements"] = user_msg.strip()
            else:
                answers[pending] = user_msg.strip()

    # Find next missing
    next_slot = None
    for s in ORDERED_REQUIRED_SLOTS:
        if not answers.get(s):
            next_slot = s
            break
    if not next_slot and "remarks_requirements" not in answers:
        next_slot = "remarks_requirements"

    if next_slot:
        return answers, QUESTION_PROMPTS[next_slot], False
    else:
        return answers, "ALL COMPLETE", True

# Simulate full flow with numbers
answers = {"first_name": "Shailendra"}
steps = ["1", "2", "2", "2", "2", "skip"]

for i, step in enumerate(steps, 1):
    answers, reply, complete = process_turn(answers, step)
    print(f"Step {i} input: {step}")
    print(f"Reply:\n{reply}\nComplete: {complete}\n")

assert complete is True
assert answers["location_preference"].startswith("Haldwani")
assert answers["planning_to_buy"] == "1 to 3 months"
assert answers["budget_range"] == "₹30 lakh to ₹50 lakh"
assert answers["payment_option"] == "Home loan"
assert answers["bhk_preference"] == "2 BHK"
assert answers["remarks_requirements"] == "None"
print("STEP BY STEP SIMULATION PASSED!")

