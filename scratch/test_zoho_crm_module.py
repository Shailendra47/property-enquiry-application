import sys
sys.path.insert(0, ".")
import zoho_crm

print("Testing zoho_crm validation and hot lead qualification...")

# Test 1: Dummy data rejection
dummy_lead = {
    "full_name": "Test Integration User",
    "email": "test@example.com",
    "mobile_number": "+919876543210",
    "planning_to_buy": "Immediately",
    "budget_range": "1 crore - 2 crore"
}
q1 = zoho_crm.evaluate_lead_quality(dummy_lead)
assert q1["is_valid"] is False, f"Expected invalid, got: {q1}"
print("[PASS] Dummy lead rejected by validation:", q1["validation_errors"])

# Test 2: Valid Hot Lead (Urgent buyer 1Cr+)
hot_lead_1 = {
    "first_name": "Himanshu",
    "last_name": "Joshi",
    "email": "hj1903954@gmail.com",
    "mobile_number": "+918057858023",
    "location_preference": "Haldwani, Uttarakhand",
    "planning_to_buy": "Within 1 Month",
    "budget_range": "1 crore - 2 crore",
    "payment_option": "Part Cash + Home Loan",
    "bhk_preference": "3 BHK"
}
q2 = zoho_crm.evaluate_lead_quality(hot_lead_1)
assert q2["is_valid"] is True, f"Expected valid, got errors: {q2['validation_errors']}"
assert q2["is_hot"] is True, f"Expected hot lead, got: {q2}"
assert q2["rating"] == "Hot"
print(f"[PASS] Hot lead qualified (Score: {q2['score']}/100, Triggers: {q2['triggers']})")

# Test 3: Cash Buyer (Hot)
cash_lead = {
    "first_name": "Rudra",
    "last_name": "Singh Deo",
    "email": "rudra@gmail.com",
    "mobile_number": "+919068978137",
    "location_preference": "Dehradun",
    "planning_to_buy": "Within 3 Months",
    "budget_range": "50 lakh - 1 crore",
    "payment_option": "Full Cash Payment",
    "bhk_preference": "Villa"
}
q3 = zoho_crm.evaluate_lead_quality(cash_lead)
assert q3["is_valid"] is True
assert q3["is_hot"] is True
assert q3["rating"] == "Hot"
print(f"[PASS] Cash buyer hot lead qualified (Score: {q3['score']}/100, Triggers: {q3['triggers']})")

# Test 4: Calendly direct meeting booked (Automatic Hot)
calendly_lead = {
    "full_name": "Monu Bisht",
    "email": "timesprpoerty@gmail.com",
    "mobile_number": "+919163988734",
    "calendly_event_name": "Real Estate Consultation Call",
    "calendly_start_time": "2026-10-28T11:00:00Z"
}
q4 = zoho_crm.evaluate_lead_quality(calendly_lead)
assert q4["is_valid"] is True
assert q4["is_hot"] is True
assert q4["rating"] == "Hot"
print(f"[PASS] Calendly booking hot lead qualified (Score: {q4['score']}/100, Triggers: {q4['triggers']})")

# Test 5: Cold Lead (Just exploring, low budget, no timeline)
cold_lead = {
    "first_name": "Casual",
    "last_name": "Browser",
    "email": "browser@gmail.com",
    "mobile_number": "+919871234567",
    "location_preference": "Haldwani",
    "planning_to_buy": "Just Exploring / Researching",
    "budget_range": "Up to 25 lakh",
    "payment_option": "Need Financial Guidance",
    "bhk_preference": "1 BHK"
}
q5 = zoho_crm.evaluate_lead_quality(cold_lead)
assert q5["is_valid"] is True
assert q5["is_hot"] is False, f"Expected cold lead, got hot: {q5}"
assert q5["rating"] == "Cold"
print(f"[PASS] Cold lead filtered out (Score: {q5['score']}/100, Rating: {q5['rating']})")

# Test 6: Raw contact submission (No requirements specified yet)
raw_contact = {
    "full_name": "Pooja Negi",
    "email": "pooja.negi@gmail.com",
    "contact_number": "+919837123987",
    "whatsapp_opt_in": True
}
q6 = zoho_crm.evaluate_lead_quality(raw_contact)
assert q6["is_valid"] is True
assert q6["is_hot"] is False
assert q6["rating"] == "Cold"
print(f"[PASS] Raw contact lead marked cold (Score: {q6['score']}/100, Rating: {q6['rating']})")

print("\nAll qualification and validation tests PASSED successfully!")
