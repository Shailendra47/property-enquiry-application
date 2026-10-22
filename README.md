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

**Contact Us workflow:** The form collects name, email, and international phone number, plus required WhatsApp consent. On submit, the contact is saved in MongoDB and the salesperson notification and customer confirmation emails are queued. The browser then opens WhatsApp with `Hi` prefilled. A registered Twilio sender also sends the approved opening template; the customer taps Send on the WhatsApp handoff to begin or continue the chat. The bot asks for location, planning timeline, budget, payment option, BHK, and remarks. It saves the completed lead in `property_leads`, linked to the original contact, then sends the Calendly link. A Calendly webhook or callback records booking details and queues the WhatsApp confirmation. Use an HTTPS public host for Twilio and Calendly webhooks.

Set `SALES_EMAIL` in `.env` to choose the salesperson notification recipient. If omitted, the app uses `SMTP_USER`. Twilio business-initiated greetings require an approved template and registered sender. The shared Sandbox cannot send custom templates; the customer must join and send the prefilled `Hi` to open the session.

The start template includes placeholders for the customer's name, email, and phone, and begins with “Hi”. Create the updated `property_contact_start_v2` template with `python create_twilio_content.py --start-only`, submit it for WhatsApp approval, and save its new Content SID as `TWILIO_WHATSAPP_START_TEMPLATE_SID`. In Sandbox mode, the app does not send this custom template; the customer must join the Sandbox and send the prefilled `Hi`. The shared `+14155238886` number is the Sandbox sender; custom templates are unavailable there, so booking tests use Twilio's built-in appointment reminder template.

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
