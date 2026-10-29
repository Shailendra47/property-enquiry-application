import sys
sys.path.insert(0, ".")
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from main import app

print("Testing POST /enquiry and GET /thank-you endpoints...")

with TestClient(app) as client:
    # -------------------------------------------------------------------
    # Test 1: Reject if consent is not checked
    # -------------------------------------------------------------------
    res_no_consent = client.post(
        "/enquiry",
        data={
            "first_name": "Deepak",
            "last_name": "Rawat",
            "email": "deepak@gmail.com",
            "country_code": "+91",
            "phone": "9876543210",
            "query": "Looking for 2 BHK",
            "whatsapp_consent": "false",
        },
        follow_redirects=False,
    )
    assert res_no_consent.status_code == 422, f"Expected 422, got {res_no_consent.status_code}"
    print("[PASS] Test 1: Rejected when whatsapp_consent is false (422)")

    # -------------------------------------------------------------------
    # Test 2: Reject if phone number is invalid
    # -------------------------------------------------------------------
    res_invalid_phone = client.post(
        "/enquiry",
        data={
            "first_name": "Deepak",
            "last_name": "Rawat",
            "email": "deepak@gmail.com",
            "country_code": "+91",
            "phone": "12345",
            "query": "Looking for 2 BHK",
            "whatsapp_consent": "true",
        },
        follow_redirects=False,
    )
    assert res_invalid_phone.status_code == 422, f"Expected 422, got {res_invalid_phone.status_code}"
    print("[PASS] Test 2: Rejected when phone number is invalid (422)")

    # -------------------------------------------------------------------
    # Test 3: Successful form submission (form-data)
    # -------------------------------------------------------------------
    with patch("main.send_whatsapp_thankyou_template") as mock_twilio_send, \
         patch("main.sync_zoho_lead"):

        res_success = client.post(
            "/enquiry",
            data={
                "first_name": "Deepak",
                "last_name": "Rawat",
                "email": "deepak.rawat@example.in",
                "country_code": "+91",
                "phone": "9876543210",
                "query": "Interested in villa in Nainital",
                "whatsapp_consent": "true",
            },
            follow_redirects=False,
        )

        assert res_success.status_code == 303, f"Expected 303, got {res_success.status_code}"
        location_header = res_success.headers.get("location")
        assert location_header.startswith("/thank-you?name=Deepak+Rawat"), f"Unexpected location: {location_header}"
        print("[PASS] Test 3: 303 Redirect to:", location_header)

        # Verify background task was called with variables {{1}}=name, {{2}}=email
        assert mock_twilio_send.called
        call_args = mock_twilio_send.call_args[0]
        assert call_args[0] == "+919876543210", f"Wrong phone: {call_args[0]}"
        assert call_args[1] == "Deepak Rawat", f"Wrong name: {call_args[1]}"
        assert call_args[2] == "deepak.rawat@example.in", f"Wrong email: {call_args[2]}"
        print("[PASS] Test 4: Background task sent Twilio template with variables {{1}}=Deepak Rawat, {{2}}=email")

    # -------------------------------------------------------------------
    # Test 4: Successful JSON submission
    # -------------------------------------------------------------------
    with patch("main.send_whatsapp_thankyou_template") as mock_twilio_send, \
         patch("main.sync_zoho_lead"):

        res_json = client.post(
            "/enquiry",
            json={
                "first_name": "Sunita",
                "last_name": "Pant",
                "email": "sunita.pant@example.in",
                "country_code": "+91",
                "phone": "9812345678",
                "query": "Commercial plot near highway",
                "whatsapp_consent": True,
            },
            follow_redirects=False,
        )
        assert res_json.status_code == 303
        assert "/thank-you?name=Sunita+Pant" in res_json.headers.get("location")
        print("[PASS] Test 5: JSON submission also redirected 303 to /thank-you?name=Sunita+Pant")

    # -------------------------------------------------------------------
    # Test 5: GET /thank-you with XSS name escaping
    # -------------------------------------------------------------------
    xss_name = "<script>alert('pwned')</script> John Doe"
    res_thankyou = client.get(f"/thank-you?name={xss_name}")
    assert res_thankyou.status_code == 200
    html_text = res_thankyou.text
    assert "<script>" not in html_text, "Unescaped <script> found!"
    assert "&lt;script&gt;alert(&#x27;pwned&#x27;)&lt;/script&gt; John Doe" in html_text or "&lt;script&gt;" in html_text
    assert "Thank You," in html_text
    print("[PASS] Test 6: GET /thank-you renders escaped name and returns 200 OK HTML")

print("\nAll enquiry & thank-you tests PASSED successfully!")

