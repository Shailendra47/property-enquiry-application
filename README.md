# Property Contact Form + WhatsApp Questionnaire + CRM

A FastAPI application with two customer forms, a Twilio WhatsApp questionnaire, MongoDB persistence, and a protected CRM dashboard.

## Quick start

1. Read [STEP_BY_STEP_GUIDE.md](STEP_BY_STEP_GUIDE.md) for MongoDB, Twilio, webhook, Sandbox, and production setup.
2. Create a virtual environment and install dependencies:

   ```bat
   py -m venv .venv
   .venv\Scripts\activate
   python -m pip install -r requirements.txt
   copy .env.example .env
   ```

3. Fill `.env` with private MongoDB, Twilio, and admin settings.
4. Start the app:

   ```bat
   python -m uvicorn main:app --reload --port 8000
   ```

5. Open the Contact Us form at `http://127.0.0.1:8000/`, the property enquiry form at `/enquiry`, or CRM login at `/admin/login`.

**WhatsApp:** Contact Us needs only name, email, and phone; no requirement text is needed. If the customer checks the optional WhatsApp questionnaire checkbox and submits the form, the app saves the opt-in. It sends the submitted details and first location question to that number. A registered sender uses an approved template; the Twilio Sandbox sends free-form text only while the customer's session is open, so each test customer must first join the Sandbox. If unchecked, the app saves the contact without starting a WhatsApp conversation. Customer replies return to `/webhooks/whatsapp`. Use an HTTPS public host (ngrok for local testing) for inbound webhooks.

The production start template includes placeholders for the customer's name, email, and phone. After creating and approving it, use its Content SID in `.env`; the app fills those placeholders from the submitted form. In Sandbox mode, the app sends the same details and first question as free-form text during an open 24-hour customer service window.

Never share `.env`; it contains credentials. The supplied `.env.example` is safe to copy and fill in.
