import sys
sys.path.insert(0, ".")
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

print("Testing /api/contact with first_name, last_name, and requirement...")

with TestClient(app) as client:
    # Test 1: Sending first_name and last_name separately + requirement
    payload1 = {
        "first_name": "Rohan",
        "last_name": "Sharma",
        "email": "rohan.sharma.test@gmail.com",
        "contact_number": "+919876543219",
        "requirement": "Looking for 3 BHK luxury apartment in Haldwani",
        "whatsapp_opt_in": False
    }
    resp1 = client.post("/api/contact", json=payload1)
    print("Status Code 1:", resp1.status_code)
    print("Response 1:", resp1.json())
    assert resp1.status_code == 201

    # Test 2: Sending full_name (backwards compatibility)
    payload2 = {
        "full_name": "Kavita Bisht",
        "email": "kavita.bisht.test@gmail.com",
        "contact_number": "+919876543218",
        "requirement": "Plot in Bhimtal near lake",
        "whatsapp_opt_in": False
    }
    resp2 = client.post("/api/contact", json=payload2)
    print("Status Code 2:", resp2.status_code)
    print("Response 2:", resp2.json())
    assert resp2.status_code == 201

print("\nAPI tests PASSED!")
