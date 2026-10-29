import os
import sys
from pathlib import Path
from starlette.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Test imports
from main import app
from twilio.request_validator import RequestValidator

# Disable signature check during test
auth_token = os.getenv("TWILIO_AUTH_TOKEN", "test_token")
public_url = os.getenv("PUBLIC_BASE_URL", "https://unlucky-walnut-boneless.ngrok-free.dev")

client = TestClient(app)

# Generate valid Twilio signature for test
validator = RequestValidator(auth_token)
params = {
    "From": "whatsapp:+917827633395",
    "Body": "Hi",
}
webhook_url = f"{public_url}/webhooks/whatsapp"
signature = validator.compute_signature(webhook_url, params)

response = client.post(
    "/webhooks/whatsapp",
    data=params,
    headers={"X-Twilio-Signature": signature},
)

print(f"Status: {response.status_code}")
print("Response text:")
print(response.text[:400])
assert response.status_code == 200, f"Expected 200, got {response.status_code}"
assert "Profilent" in response.text, "Response must contain 'Profilent'"
assert "Which area are you interested in" in response.text or "हल्द्वानी" in response.text, "Must ask location question"
print("\nWEBHOOK GREETING TEST PASSED!")

