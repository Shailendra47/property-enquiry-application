# Contact form WhatsApp questionnaire

For the full project installation, webhook setup, test steps, and delivery checklist, see [STEP_BY_STEP_GUIDE.md](STEP_BY_STEP_GUIDE.md).

The completed WhatsApp questionnaire shares the Calendly URL. Expose the app over HTTPS (ngrok locally, or your hosted URL in production) and subscribe Calendly `invitee.created` to `https://YOUR_PUBLIC_HOST/webhooks/calendly`. Set `CALENDLY_WEBHOOK_SIGNING_KEY` and `TWILIO_WHATSAPP_BOOKING_TEMPLATE_SID` in `.env`. Run `python create_twilio_content.py --booking-only` to create just the appointment template, submit it for WhatsApp approval in Twilio Console, then paste its printed Content SID into `.env` and restart the app. The app sends free-form text inside the 24-hour customer window and uses the approved booking template outside it (or as a fallback if free-form sending is rejected). `TWILIO_WHATSAPP_FROM` is the sender; the matched, opted-in enquiry number is the recipient. Calendly retries are de-duplicated by invitee URI.

## Connected pages and CRM

- `/` opens the Contact Us form.
- `/enquiry` opens the detailed property enquiry form.
- `/admin/login` opens the protected CRM login; after login, `/admin` shows the overview and combined **All Leads** list, with separate editable views for each form.
- Contact Us submissions are stored in the MongoDB `contacts` collection. Property form and completed WhatsApp questionnaire records are stored in `property_leads` by default. The CRM reads both collections, so leads from either customer form appear in the same dashboard.
- The CRM overview includes All Leads, separate editable lists, links to both public forms, and a Twilio configuration indicator. The indicator checks local settings and webhook URL format; it cannot confirm approval or delivery in Twilio.

Set `ADMIN_USERNAME`, `ADMIN_PASSWORD`, and a long random `SESSION_SECRET` in `.env` before using the CRM.

When a visitor submits Contact Us, the required WhatsApp consent is saved with their contact. The app queues a salesperson email to `SALES_EMAIL` (defaults to `SMTP_USER`) and a customer confirmation email, then opens WhatsApp with `Hi` prefilled. A registered Twilio sender sends the approved start template containing the submitted name, email, phone, and location question. The customer taps Send to open the conversation. The Sandbox cannot use custom templates; the recipient must join it and send `Hi`, after which the bot asks the location question in the active session. Conversation state is stored in MongoDB's `whatsapp_conversations`. The bot continues with planning timeline, budget, payment option, BHK, and remarks. On completion, it upserts the lead in `property_leads`, links it to the original contact, and sends the Calendly link.

The flow validates first name and email, supports skip for last name and remarks, confirms or replaces the mobile number, and uses native WhatsApp list pickers for planning, budget, payment categories/sub-options, and BHK. Payment options use separate category and sub-option menus so no list exceeds WhatsApp's 10-row limit.

## Configure Twilio

1. Install the supported dependencies: `python -m pip install -r requirements.txt`.
2. Copy `.env.example` to `.env`. Fill in `MONGODB_URI`, Twilio account SID and Auth Token, WhatsApp sender number, and the public HTTPS `PUBLIC_BASE_URL`. Keep `.env` private.
3. Run `python create_twilio_content.py` once to create Content API templates. Copy the printed Content SIDs into the matching `.env` entries.
4. Run `python create_twilio_content.py --start-only` to create `property_contact_start_v2`. Submit it for approval and set its returned SID as `TWILIO_WHATSAPP_START_TEMPLATE_SID`. The form-triggered first message requires a registered WhatsApp sender, customer consent, and the approved start template. Booking confirmations use free-form text inside the 24-hour window and the approved booking template after it closes. List pickers and quick replies are used after the recipient responds.
5. Configure the WhatsApp sender's incoming-message webhook in Twilio as `https://YOUR_PUBLIC_HOST/webhooks/whatsapp`, method `POST`. The host must exactly match `PUBLIC_BASE_URL` in `.env`.
6. Run the app on a publicly reachable HTTPS host. When a customer submits Contact Us, the server stores the contact and attempts to send the start template. The page reports whether Twilio accepted that start message. A Twilio-accepted message may still be queued; check Twilio Messaging Logs for delivery status.

The Contact Us form asks for name, email, and an international-format phone number, plus required explicit consent for WhatsApp messages. `SALES_EMAIL` chooses the salesperson notification recipient; when omitted, the app sends it to `SMTP_USER`. Keep `.env` private; never distribute it. If SMTP or Twilio rejects a message, check the app terminal and the corresponding service logs.

## Sandbox testing

The Sandbox is intended for testing and can message only joined numbers. It cannot use the custom property start template. For production form-triggered greetings, run `python create_twilio_content.py --start-only`, submit `property_contact_start_v2` for approval, and set the returned SID as `TWILIO_WHATSAPP_START_TEMPLATE_SID`. To test in Sandbox, join the test phone, submit the form, and send the prefilled `Hi`; the bot starts the location question inside the open session.

WhatsApp list-picker messages cannot start a business-initiated conversation; they are only sent after the recipient replies and opens the 24-hour window. See [Twilio's list-picker docs](https://www.twilio.com/docs/content/twiliolist-picker), [WhatsApp session rules](https://www.twilio.com/docs/whatsapp/key-concepts), and [template setup](https://www.twilio.com/docs/whatsapp/tutorial/send-whatsapp-notification-messages-templates).
