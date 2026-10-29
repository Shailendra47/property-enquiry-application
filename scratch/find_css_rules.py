import re

with open('static/style.css', 'r', encoding='utf-8') as f:
    css = f.read()

# Let's search for rules with wk-ipadp-6 or wk-desk-12 or input-title or section-title-wrap
rules = re.findall(r'([^{}]+)\{([^{}]+)\}', css)
for sel, body in rules:
    sel = sel.strip()
    if any(k in sel for k in ['wk-ipadp-6', 'wk-desk-6', 'wk-desk-12', 'input-title', 'loc-wrap', 'first_name', 'location_preference', 'section-title']):
        print(f"--- {sel} ---")
        for line in body.strip().split(';'):
            line = line.strip()
            if line:
                print(f"    {line}")

