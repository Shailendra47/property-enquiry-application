import sys
sys.stdout.reconfigure(encoding='utf-8')

form_data = {
    'first_name': 'Shailendra',
    'location_preference': 'Haldwani',
    'bhk_preference': 'Residential Plot',
    'budget_range': '25-30 Lakh',
    'planning_to_buy': 'Within 3 Months',
    'payment_option': 'Home Loan',
    'req': 'Parking'
}

req_line = f"• *Special Requirements:* {form_data['req']}\n" if form_data['req'] else ""
end_message = (
    f"✅ *Thank you, {form_data['first_name']}!* I've noted down all your requirements:\n\n"
    f"• *Location:* {form_data['location_preference']}\n"
    f"• *Configuration:* {form_data['bhk_preference']}\n"
    f"• *Budget:* {form_data['budget_range']}\n"
    f"• *Timeline:* {form_data['planning_to_buy']}\n"
    f"• *Payment Option:* {form_data['payment_option']}\n"
    f"{req_line}\n"
    f"Our property specialist team will review your preferences and share hand-picked options.\n\n"
    f"📅 *Schedule a 1-on-1 consultation at your convenience:* \nhttps://calendly.com/shailendra-profilent/30min\n\n"
    f"💬 *If you'd like to update any details or have more questions, feel free to message me here anytime!*"
)

print("=== GENERATED ENQUIRY END MESSAGE ===")
print(end_message)
assert "✅ *Thank you, Shailendra!*" in end_message
assert "• *Location:* Haldwani" in end_message
assert "• *Special Requirements:* Parking" in end_message
assert "Which city or area" not in end_message
print("ALL ASSERTIONS PASSED!")

