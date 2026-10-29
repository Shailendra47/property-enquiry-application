import sys
import re

sys.stdout.reconfigure(encoding='utf-8')

HINGLISH_WORDS = re.compile(
    r'\b(mujhe|chahiye|aap|aapka|aapko|hai|hain|kya|bhai|karna|hoga|batao|bataiye|'
    r'kitna|kitne|mein?|se|ke|liye|ka|ki|ko|nahi|nahin|dhanyawad|ghar|makan|zameen|'
    r'raha|rahe|karein|bhi|aur|kaun|kaunsa|kab|tak|dekh|baat|karo|batao|shukriya)\b',
    re.IGNORECASE
)

def detect_language(text: str, current_lang: str = "en") -> str:
    if not text:
        return current_lang
    if re.search(r"[\u0900-\u097F]", text):
        return "hi"
    if HINGLISH_WORDS.search(text):
        return "hinglish"
    return current_lang

tests = [
    ("I want a 2 BHK apartment in Haldwani", "en"),
    ("नमस्ते मुझे हल्द्वानी में 2 बीएचके चाहिए", "hi"),
    ("mujhe 2 bhk flat chahiye haldwani me", "hinglish"),
    ("bhai budget 40 lakh hai", "hinglish"),
    ("what is the price of villa", "en"),
    ("budget kitna lagega", "hinglish"),
    ("1", "hinglish"),  # should retain previous language
]

for t, expected in tests:
    res = detect_language(t, current_lang="hinglish" if t == "1" else "en")
    print(f'"{t}" -> {res} (expected: {expected})')
    assert res == expected
print("\nLANGUAGE DETECTION TESTS PASSED!")

