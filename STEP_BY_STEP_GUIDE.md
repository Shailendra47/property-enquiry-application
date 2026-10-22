# Property Contact Form, WhatsApp Bot, and CRM — Handover Guide

This guide takes the project from extraction to a working local demonstration. Keep the real `.env` file private; it contains database and Twilio credentials.

## 1. What the project does

1. The customer submits the Contact Us form with name, email, international-format phone number, and required WhatsApp consent.
2. The app saves the contact in MongoDB's `contacts` collection and queues a salesperson notification email (`SALES_EMAIL`, or `SMTP_USER` if no recipient override is set) plus the customer confirmation email.
3. The browser opens WhatsApp with `Hi` prefilled. A registered Twilio sender also sends the approved start template containing the form details and location question. The customer taps Send in WhatsApp to start the inbound session.
4. Twilio POSTs replies to `/webhooks/whatsapp`. The bot validates the location, then asks Planning to Buy, Budget Range, Payment Option, BHK Preference, and Remarks / Requirements.
5. The completed answers are saved in `property_leads` and linked to the original `contacts` record. The app queues a Zoho Lead sync and sends the customer the Calendly scheduling link.
6. When the customer books, the Calendly webhook or booking callback matches the booking to the lead by email or phone, stores the booking details, and queues an opted-in WhatsApp confirmation. The registered sender uses the approved booking template; Sandbox uses its built-in appointment reminder template.

The app provides these pages:

| Page | URL | Purpose |
| --- | --- | --- |
| Contact Us form | `/` | Captures name, email, phone, and required WhatsApp consent; then opens WhatsApp. |
| Property Enquiry form | `/enquiry` | Captures property preferences directly. |
| CRM login | `/admin/login` | Protected admin sign-in. |
| CRM dashboard | `/admin` | Overview, combined All Leads table, and separate contact/property lead management. |

## 2. Requirements

- Python 3.11 or newer.
- A MongoDB Atlas database and a connection URI.
- A Twilio account with WhatsApp Sandbox access for inbound testing, or a registered WhatsApp sender for production.
- ngrok or another HTTPS tunnel for local webhook testing. For production, deploy the app on a stable public HTTPS host.

## 3. Extract and install

Open Command Prompt in the extracted `property-contact-form` folder. This folder should contain `main.py`, `whatsapp_bot.py`, and `requirements.txt`.

```bat
py -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
copy .env.example .env
```

If PowerShell is being used, activate the environment with:

```powershell
.\.venv\Scripts\Activate.ps1
```

## 4. Configure MongoDB and admin access

Edit `.env` and replace the example values:

```env
MONGODB_URI=mongodb+srv://<db-user>:<db-password>@<cluster>/<database>?retryWrites=true&w=majority
DB_NAME=property_db
COLLECTION_NAME=contacts
ENQUIRY_COLLECTION_NAME=property_leads
ADMIN_USERNAME=admin
ADMIN_PASSWORD=<a-strong-private-password>
SESSION_SECRET=<a-long-random-private-string>
```

In MongoDB Atlas, create a database user and allow the host where the app runs in **Network Access**. If the database password contains URL-reserved characters, URL-encode those characters in `MONGODB_URI`.

## 5. Configure Twilio credentials and sender

Add the credentials from the same Twilio account that owns the sender and Content templates:

```env
TWILIO_ACCOUNT_SID=AC<your-account-sid>
TWILIO_AUTH_TOKEN=<your-private-auth-token>
TWILIO_WHATSAPP_FROM=+<your-whatsapp-enabled-sender-number>
TWILIO_WHATSAPP_START_TEMPLATE_SID=HX<approved-start-template-sid>
```

Use the sender in E.164 format (country code plus number), without the `whatsapp:` prefix. Do not paste the Auth Token into chat or include `.env` when sharing the project.

### Sandbox or production?

- **Sandbox inbound demonstration:** each test phone must first send the Sandbox join phrase. The form then opens the Sandbox chat with `Hi` prefilled; the customer taps Send, opening the customer-service window and receiving the location question. The Sandbox cannot use the custom property start template.
- **Automatic custom start on form submit:** use a registered WhatsApp sender and an approved start template in that sender's Twilio account. The form notice tells customers that submitting opts them in to the WhatsApp follow-up; retain this clear notice and honor `STOP` replies.

WhatsApp requires explicit opt-in and approved templates for business-initiated conversations. See [Twilio WhatsApp requirements](https://www.twilio.com/docs/whatsapp/api) and [Sandbox limitations](https://www.twilio.com/docs/whatsapp/sandbox).

## 6. Create the Content templates

With the virtual environment active and Twilio credentials saved in `.env`, run once:

```bat
python create_twilio_content.py
```

The script prints `HX...` Content SIDs. Copy each printed line into the corresponding `.env` variable, including:

- `TWILIO_WHATSAPP_START_TEMPLATE_SID`
- `TWILIO_WHATSAPP_BOOKING_TEMPLATE_SID`
- planning, budget, payment category/subcategory, and BHK list-picker SIDs
- `TWILIO_QUICK_REPLY_MOBILE_SID`

For the updated opening message, run `python create_twilio_content.py --start-only`. It creates `property_contact_start_v2`, which starts with “Hi” and includes the submitted name, email, phone, and location question. Submit it for WhatsApp approval, then set its returned SID as `TWILIO_WHATSAPP_START_TEMPLATE_SID` in `.env`. The booking template contains the customer's name and email, meeting name, start/end, timezone, location/join URL, and booking details. The start and booking templates must be approved before use with a registered sender outside the 24-hour window. The Sandbox cannot use custom templates; it uses Twilio's built-in appointment reminder template for a scheduled booking. Every Sandbox recipient must join using the `join <sandbox code>` message. The list-picker and quick-reply templates are for a registered sender. If Twilio reports `ContentSid is Invalid`, confirm the SID is an `HX...` SID from the same account and was copied without spaces.

## 7. Run the app and expose a local HTTPS webhook

Start the app in one terminal:

```bat
python -m uvicorn main:app --reload --port 8000
```

Start ngrok in a second terminal:

```bat
ngrok http 8000
```

Copy the HTTPS forwarding origin shown by ngrok, for example `https://example-id.ngrok-free.app`. Set that exact origin (no route path and no trailing slash) in `.env`:

```env
PUBLIC_BASE_URL=https://example-id.ngrok-free.app
```

Restart Uvicorn after changing `.env`. Keep both terminals running while testing. A free ngrok URL can change after restarting ngrok; update both `.env` and Twilio whenever it changes.

## 8. Set Twilio's incoming-message webhook

For Sandbox testing, open **Twilio Console → Messaging → Try it out → Send a WhatsApp message → Sandbox settings**. In **When a message comes in**, enter:

```text
https://example-id.ngrok-free.app/webhooks/whatsapp
```

Choose **POST** and save. For a registered WhatsApp sender, open **Messaging → Senders → WhatsApp Senders**, select the sender, and set its inbound-message webhook to the same URL with **POST**. The URL origin must match `PUBLIC_BASE_URL` exactly. Twilio's current webhook configuration locations are described in its [WhatsApp API guide](https://www.twilio.com/docs/whatsapp/api).

## 9. Test the project

### Test inbound chatbot replies in the Sandbox

1. Join your test phone to the Sandbox using the join phrase displayed in Twilio.
2. Send `Hi` to the Sandbox number.
3. Confirm the app terminal/ngrok shows a POST to `/webhooks/whatsapp` and that Q1 is returned.
4. Continue answering. Use `skip` for optional remarks.
5. Complete the flow, then log into `/admin/login` and open **All Leads** or **Property Enquiries**. The completed lead should appear in `property_leads`.

### Test automatic form-triggered opening message

1. Use a registered WhatsApp sender with the approved `property_contact_start_v2` template. The Sandbox cannot send this custom start template.
2. Confirm all four required outbound settings are valid: Account SID, Auth Token, registered WhatsApp sender, and approved start-template SID.
3. Open `/`, enter the name, email, and opted-in phone number, then click **Send Enquiry**. The app saves the contact, queues the salesperson email and customer confirmation, and opens WhatsApp with `Hi` prefilled.
4. Tap Send in WhatsApp. The bot starts the location question, then continues with planning date, budget, payment choice, BHK, and optional remarks. The form name, email, and phone are already attached to the conversation.
5. Confirm the completed enquiry appears in `property_leads` and is linked to the original contact. Check Twilio Messaging Logs for delivery and the `SALES_EMAIL` inbox for the salesperson notification.

## 10. Open and use the CRM

Open `http://127.0.0.1:8000/admin/login` and sign in using `ADMIN_USERNAME` and `ADMIN_PASSWORD` from `.env`.

- **Overview** shows lead counts, recent entries, and the WhatsApp configuration indicator.
- **All Leads** combines Contact Us and property enquiry records and supports search.
- **Contact Us Leads** and **Property Enquiries** have separate searchable tables with add, edit, and delete actions.
- The header links back to both forms.

The WhatsApp indicator checks local settings and HTTPS URL shape only; it cannot verify template approval, the Console webhook setting, or final delivery.

## 11. Calendly booking link and WhatsApp confirmation

The completed WhatsApp questionnaire replies with `CALENDLY_URL`. Set it in `.env` if you want a different booking page. To send a booking confirmation to the customer's WhatsApp number, deploy the app at a public HTTPS URL and configure:

```env
CALENDLY_URL=https://calendly.com/shailendra-profilent/30min
CALENDLY_WEBHOOK_SIGNING_KEY=<signing key for your Calendly webhook subscription>
CALENDLY_TOKEN=<Calendly personal access token with scheduled_events:read scope>
TWILIO_WHATSAPP_BOOKING_TEMPLATE_SID=HX<approved booking-confirmation Content SID>
```

`python create_twilio_content.py --booking-only` creates `property_calendly_booking_confirmation_v2` with the customer's name and email plus the meeting details. Put its new Content SID in `TWILIO_WHATSAPP_BOOKING_TEMPLATE_SID` and submit it for WhatsApp approval. Replace the old Content SID after approval. This custom template requires a registered WhatsApp sender; the shared `+14155238886` Sandbox sender cannot use custom templates.

For a registered sender, the app sends the approved booking template automatically after scheduling, with name and email matched from the form/Calendly invitee. If that template fails while the customer-service window is open, it falls back to free-form text. For the Sandbox, the app sends Twilio's built-in appointment reminder template, which supports date and time only. The app matches the Calendly invitee email, or an international phone from Calendly's text reminder / phone question, to the saved enquiry or WhatsApp conversation.

In Calendly, create a webhook subscription for `invitee.created` with the destination `https://YOUR_PUBLIC_HOST/webhooks/calendly`; configure its signing key to match `CALENDLY_WEBHOOK_SIGNING_KEY`. Keep `PUBLIC_BASE_URL` set to the same public host used for the Twilio webhook. The schedule page also posts Calendly's event and invitee references to `/api/calendly/booking-confirmation`; the server retrieves the booking from Calendly using `CALENDLY_TOKEN` and can send the confirmation if webhook delivery is delayed or unavailable. Both paths share one invitee URI de-duplication record, so they do not send twice. The app matches a Contact Us or WhatsApp enquiry by email or international phone, stores the booking and notification status on the matched MongoDB lead, and sends from `TWILIO_WHATSAPP_FROM` to the matched customer's WhatsApp number.

Only Contact Us leads that opted in or WhatsApp-originated enquiry leads receive a message; a saved `STOP` reply suppresses it. Twilio must have a registered WhatsApp sender and the approved confirmation template. Calendly should also have its own booking notifications enabled as a fallback.

### Test the Calendly confirmation

1. Copy `.env.example` to `.env`, fill in the private credentials, and run the app on the public HTTPS host configured in Calendly.
2. Submit Contact Us with WhatsApp opt-in, using a test email and E.164 phone number, and complete the questionnaire. Alternatively, complete a WhatsApp-originated enquiry.
3. Book a test Calendly meeting with that email. To check phone matching, provide the same international number in Calendly's text reminder number or a phone question.
4. Confirm the customer receives the meeting date, time, and timezone. In MongoDB, inspect the matched contact/lead's `calendly_booking` data and `notification.status`; check Twilio Messaging Logs and `calendly_webhook_events` for the message SID and delivery state.
5. Replay the same webhook delivery. The same Calendly invitee URI must not create a second confirmation. An unsigned request should return HTTP 403.

## 12. Troubleshooting

| Symptom | Check |
| --- | --- |
| Form says WhatsApp setup is missing | It lists missing setting names. Fill those in `.env` and restart Uvicorn. Use valid `AC...` Account SID, `HX...` Content SID, and E.164 sender. |
| Twilio rejected the start message | Read the app terminal exception and open Messaging Logs for the Twilio error code. Check that sender, recipient, template, and credentials belong to the same account. |
| ContentSid Invalid / error 21655 | Use the actual Content SID from the same account, not an example SID, message SID (`MM...`), or Account SID (`AC...`). |
| Twilio still sends the default “Configure your Sandbox Inbound URL” message | Save the exact public `/webhooks/whatsapp` URL in Sandbox settings, choose POST, and ensure ngrok and Uvicorn are running. |
| Webhook returns invalid signature | Make sure `PUBLIC_BASE_URL` exactly matches the public URL Twilio calls; update it when the ngrok address changes, then restart Uvicorn. |
| Sandbox recipient cannot receive messages | Rejoin using the current Sandbox join phrase; membership expires after 72 hours. |
| Contact form works but replies do not | Check the webhook URL and method. Localhost/127.0.0.1 cannot be reached by Twilio; use HTTPS ngrok for development or a public deployment. |
| CRM login or data fails | Set `ADMIN_PASSWORD` and `SESSION_SECRET`; verify MongoDB URI, Atlas Network Access, and that the app starts without a MongoDB error. |

## 13. Delivery checklist

- [ ] `.env` contains real settings and is excluded from the delivery ZIP.
- [ ] MongoDB Atlas is reachable from the deployment host.
- [ ] Both public forms submit successfully and records appear in CRM.
- [ ] Admin credentials are private and non-default.
- [ ] Sandbox join and inbound chatbot flow have been demonstrated.
- [ ] For automatic custom form-triggered starts, the production sender is registered and the start template is approved.
- [ ] Twilio inbound webhook points to the production HTTPS host at `/webhooks/whatsapp` with POST.
- [ ] Calendly `invitee.created` webhook points to the production HTTPS host at `/webhooks/calendly`; its signing key and the approved Twilio booking template SID are configured.
- [ ] Twilio Messaging Logs show an accepted/delivered message during the live test.
- [ ] `.env`, Auth Token, and database password are not in screenshots, source control, or the delivered ZIP.
