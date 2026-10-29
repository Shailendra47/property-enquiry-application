import html
import json
import phonenumbers
from phonenumbers import NumberParseException

print("Testing phonenumbers parsing & validation...")

def validate_phone(country_code: str, phone: str) -> str:
    clean_cc = (country_code or "+91").strip() or "+91"
    if not clean_cc.startswith("+"):
        clean_cc = f"+{clean_cc}"
    raw_phone = (phone or "").strip()
    if not raw_phone:
        raise ValueError("Phone number is required.")
    
    digits_and_plus = "".join(c for c in raw_phone if c.isdigit() or c == "+")
    if digits_and_plus.startswith("+"):
        full_number = digits_and_plus
    else:
        full_number = f"{clean_cc}{digits_and_plus.lstrip('0')}"

    try:
        parsed = phonenumbers.parse(full_number, None)
        if not phonenumbers.is_valid_number(parsed):
            raise ValueError(f"Invalid phone number '{phone}' for country code '{clean_cc}'.")
        return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
    except NumberParseException as e:
        raise ValueError(f"Phone number format parse error: {e}")

# Test valid Indian phone
p1 = validate_phone("+91", "9876543210")
assert p1 == "+919876543210", f"Got: {p1}"
print("[PASS] Valid Indian phone (+91 9876543210) ->", p1)

# Test valid US phone
p2 = validate_phone("+1", "4155552671")
assert p2 == "+14155552671", f"Got: {p2}"
print("[PASS] Valid US phone (+1 4155552671) ->", p2)

# Test invalid phone
try:
    validate_phone("+91", "1234")
    assert False, "Should have failed"
except ValueError as e:
    print("[PASS] Invalid phone rejected:", e)

# Test XSS escaping
raw_name = "<script>alert('xss')</script> John & Jane"
safe_name = html.escape(raw_name)
assert "<script>" not in safe_name
assert "&lt;script&gt;" in safe_name
assert "&amp;" in safe_name
print("[PASS] XSS protection verified:", safe_name)

print("\nAll unit tests PASSED!")

