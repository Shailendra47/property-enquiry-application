import sys
sys.path.insert(0, ".")
from unittest.mock import patch
import zoho_crm

print("Testing sync_zoho_lead gatekeeper...")

with patch("zoho_crm.zoho_is_configured", return_value=True), \
     patch("zoho_crm._get_access_token", return_value="mock_token"), \
     patch("zoho_crm._update_mongo_lead_status") as mock_update, \
     patch.object(zoho_crm._session, "post") as mock_post:

    # Case 1: Unvalidated lead (dummy name / email)
    dummy_lead = {
        "full_name": "Test Integration User",
        "email": "test@example.com",
        "mobile_number": "+919876543210",
        "planning_to_buy": "Immediately",
        "budget_range": "1 crore - 2 crore"
    }
    res1 = zoho_crm.sync_zoho_lead(dummy_lead)
    assert res1 is None
    assert not mock_post.called, "Network post should NOT be called for invalid lead"
    assert mock_update.called
    call_args = mock_update.call_args[1]
    assert call_args["status"] == "skipped_invalid"
    print("[PASS] Gate 1: Unvalidated lead rejected and recorded as 'skipped_invalid'")

    mock_update.reset_mock()
    mock_post.reset_mock()

    # Case 2: Valid lead, but cold / unqualified
    cold_lead = {
        "first_name": "Shailendra",
        "last_name": "Kumar",
        "email": "shailendra@gmail.com",
        "mobile_number": "+919876512345",
        "planning_to_buy": "Just Exploring / Researching",
        "budget_range": "Up to 25 lakh"
    }
    res2 = zoho_crm.sync_zoho_lead(cold_lead)
    assert res2 is None
    assert not mock_post.called, "Network post should NOT be called for cold lead"
    assert mock_update.called
    call_args = mock_update.call_args[1]
    assert call_args["status"] == "skipped_cold"
    print("[PASS] Gate 2: Cold lead rejected and recorded as 'skipped_cold'")

    mock_update.reset_mock()
    mock_post.reset_mock()

    # Case 3: Valid Hot Lead
    hot_lead = {
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
    mock_post.return_value.status_code = 200
    mock_post.return_value.ok = True
    mock_post.return_value.json.return_value = {
        "data": [{"status": "success", "details": {"id": "zoho_hot_12345"}}]
    }

    res3 = zoho_crm.sync_zoho_lead(hot_lead)
    assert res3 == "zoho_hot_12345"
    assert mock_post.called, "Network post SHOULD be called for hot lead"
    assert mock_update.called
    call_args = mock_update.call_args[1]
    assert call_args["status"] == "synced"
    assert call_args["zoho_lead_id"] == "zoho_hot_12345"
    assert call_args["rating"] == "Hot"
    
    # Inspect the payload sent to Zoho
    sent_payload = mock_post.call_args[1]["json"]["data"][0]
    assert sent_payload["Rating"] == "Hot"
    assert sent_payload["Lead_Status"] == "Qualified"
    assert "[QUALIFIED HOT LEAD - HIGH INTENT PROPERTY BUYER]" in sent_payload["Description"]
    print("[PASS] Gate 3: Hot lead allowed, payload enriched with 'Rating': 'Hot', status 'Qualified', and synced")

print("\nAll gatekeeper tests PASSED successfully!")

