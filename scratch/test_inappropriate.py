import sys
import re

sys.stdout.reconfigure(encoding='utf-8')

_INAPPROPRIATE_PATTERN = re.compile(
    r'\b('
    # English vulgarities, insults, abuse
    r'fuck|fucking|fucker|shit|bitch|bastard|asshole|dick|cock|pussy|porn|nude|sex|sexy|horny|'
    r'idiot|stupid|dumb|shut\s*up|kill\s*yourself|useless|scam|fraud|cheat|loot|chor|'
    # Hindi / Hinglish abuse & slang
    r'chutiya|chutiye|madarchod|bhosdike|bhosadi|gaand|gandu|harami|kameena|saale|saala|kutta|kutte|'
    r'bewakoof|pagal|bakwas|bakwaas|lund|lauda|randi|terimak|bc|mc'
    r')\b',
    re.IGNORECASE
)

# Keyboard smash / gibberish pattern
_GIBBERISH_PATTERN = re.compile(
    r'(\b(asdf|qwerty|zxcv|hjkl|dfgh)\w*\b|([a-zA-Z])\3{4,}|\b[bcdfghjklmnpqrstvwxyz]{5,}\b)',
    re.IGNORECASE
)

def is_inappropriate(text: str) -> bool:
    if not text:
        return False
    if _INAPPROPRIATE_PATTERN.search(text):
        return True
    if _GIBBERISH_PATTERN.search(text):
        return True
    return False

positives = [
    'you are stupid',
    'fuck off',
    'ye sab bakwas hai',
    'chutiya bot',
    'shut up',
    'pagal ho kya',
    'asdfghjkl',
    'what a scam',
    'bitch',
]

negatives = [
    'i need 2 bhk in haldwani',
    'commercial space in dwarka for 25-30 lakh',
    'Coordinate via WhatsApp chat only',
    'afternoon slot',
    'please provide me options',
    'what is the price of villa?',
    'i got a job in haldwani',
    'can i schedule a meeting with calendly?',
]

print("TESTING POSITIVES:")
for p in positives:
    res = is_inappropriate(p)
    print(f'"{p}" -> {res}')
    assert res is True, f"Failed positive: {p}"

print("\nTESTING NEGATIVES:")
for n in negatives:
    res = is_inappropriate(n)
    print(f'"{n}" -> {res}')
    assert res is False, f"Failed negative: {n}"

print("\nALL POSITIVE AND NEGATIVE TESTS PASSED!")
