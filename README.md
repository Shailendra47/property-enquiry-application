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

3. Fill `.env` with private MongoDB, Twilio, Calendly webhook, and admin settings listed in `.env.example`.
4. Start the app:

   ```bat
   python -m uvicorn main:app --reload --port 8000
   ```

5. Open the Contact Us form at `http://127.0.0.1:8000/`, the property enquiry form at `/enquiry`, or CRM login at `/admin/login`.

### Troubleshooting: `cannot import name 'ObjectId' from 'bson'`

Run the app using the project's virtual environment so it uses the `bson` module bundled with PyMongo:

```bat
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m uvicorn main:app --reload --port 8000
```

Do not install the separate `bson` package; PyMongo provides the `bson` module. If you installed `bson` into a different Python environment, remove it there with `python -m pip uninstall bson`, then reinstall PyMongo with `python -m pip install --force-reinstall pymongo`.

**WhatsApp:** Contact Us needs only name, email, and phone; no requirement text is needed. If the customer checks the optional WhatsApp questionnaire checkbox and submits the form, the app saves the opt-in. It sends the submitted details and first location question to that number. A registered sender uses an approved template; the Twilio Sandbox sends free-form text only while the customer's session is open, so each test customer must first join the Sandbox. If unchecked, the app saves the contact without starting a WhatsApp conversation. Customer replies return to `/webhooks/whatsapp`. Use an HTTPS public host (ngrok for local testing) for inbound webhooks.

The production start template includes placeholders for the customer's name, email, and phone. After creating and approving it, use its Content SID in `.env`; the app fills those placeholders from the submitted form. In Sandbox mode, the app sends the same details and first question as free-form text during an open 24-hour customer service window.

Never share `.env`; it contains credentials. The supplied `.env.example` is safe to copy and fill in.
# Zoho CRM

Website contact submissions, property enquiries, and completed WhatsApp questionnaires are synced to Zoho CRM in the background as Leads. The local MongoDB save and customer response do not depend on Zoho availability. Records are upserted using email and phone to reduce duplicates.

Configure these values in your local .env (see .env.example):

- ZOHO_CLIENT_ID, ZOHO_CLIENT_SECRET: OAuth client credentials.
- ZOHO_REFRESH_TOKEN: long-lived refresh token created after authorizing the client for Zoho CRM.
- ZOHO_ACCOUNTS_URL, ZOHO_API_DOMAIN: use the URLs for your Zoho data center; .in is the default.
- ZOHO_MODULE: defaults to Leads.
- ZOHO_DEFAULT_COMPANY: value sent for Zoho's required Company field.

Authorize the Zoho OAuth client with the CRM Leads scope (ZohoCRM.modules.leads.ALL), offline access, and the exact redirect URI registered in Zoho. Exchange a newly generated authorization code at {ZOHO_ACCOUNTS_URL}/oauth/v2/token using grant_type=authorization_code, client_id, client_secret, redirect_uri, and code; copy the returned refresh_token into .env. Authorization codes expire quickly and must not be used as refresh tokens. Restart the app after updating .env.

The OAuth client secret was visible in the shared screenshot. Rotate it in Zoho before putting the replacement in .env; also generate a new authorization code rather than using the temporary code shown there.

Zoho's Leads module must have the standard First_Name, Last_Name, Company, Email, Phone, Mobile, and Description fields available. CRM sync errors are logged and do not fail an enquiry submission.
