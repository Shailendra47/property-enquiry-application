"""Generate high-resolution PNG files for all 6 project workflows and save to image/workflows and static/workflows."""

import base64
import os
from pathlib import Path
import requests

BASE_DIR = Path(__file__).resolve().parent.parent
IMAGE_DIR = BASE_DIR / "image" / "workflows"
STATIC_DIR = BASE_DIR / "static" / "workflows"

IMAGE_DIR.mkdir(parents=True, exist_ok=True)
STATIC_DIR.mkdir(parents=True, exist_ok=True)

WORKFLOWS = {
    "workflow_1_master_architecture": {
        "title": "Complete Master System Architecture",
        "description": "End-to-End System Architecture across Website, FastAPI, Twilio WhatsApp, Gemini AI, Zoho CRM, Calendly, and Admin CRM.",
        "mermaid": """flowchart TD
    %% Styling Classes
    classDef primary fill:#2A9DAE,stroke:#1e7482,stroke-width:2px,color:#ffffff;
    classDef secondary fill:#f1f5f9,stroke:#cbd5e1,stroke-width:1.5px,color:#1e293b;
    classDef database fill:#ffffff,stroke:#2A9DAE,stroke-width:2px,color:#0f172a;
    classDef hot fill:#fef2f2,stroke:#dc2626,stroke-width:2px,color:#991b1b;
    classDef external fill:#fff7ed,stroke:#ea580c,stroke-width:1.5px,color:#9a3412;
    classDef accent fill:#e0f2fe,stroke:#0284c7,stroke-width:1.5px,color:#0369a1;

    %% Entry Points
    subgraph S1["1. Client Entry Points"]
        V["Website Visitor"] --> W1["Contact Us Page<br/>(/ - index.html)"]
        V --> W2["Property Enquiry Page<br/>(/enquiry - enquiry.html)"]
        V --> W3["WhatsApp Direct Chat<br/>(wa.me / Twilio Sandbox)"]
        V --> W4["Calendly Schedule<br/>(/schedule)"]
    end

    %% FastAPI Engine
    subgraph S2["2. FastAPI Backend Engine (main.py)"]
        W1 -->|"Submit Contact Form"| EP1["POST /api/contact"]
        W2 -->|"Submit Property Form"| EP2["POST /api/enquiry"]
        W2 -.->|"Search Locations"| EP3["GET /api/locations<br/>(Photon / OSM)"]

        EP1 --> VAL1["Validate Schema<br/>(ContactForm)"]
        EP2 --> VAL2["Validate Schema<br/>(PropertyEnquiryForm)"]

        VAL1 --> BG["Background Tasks Queue"]
        VAL2 --> BG
    end

    %% Database Storage
    subgraph S3["3. MongoDB Atlas Database Layer"]
        VAL1 --> DB1[("contacts<br/>Collection")]
        VAL2 --> DB2[("property_leads<br/>Collection")]
        DB3[("whatsapp_conversations<br/>Collection")]
        DB4[("upserted_leads<br/>Unified Collection")]
        DB5[("appointments<br/>Collection")]
    end

    %% WhatsApp AI Engine
    subgraph S4["4. WhatsApp AI Conversational Bot"]
        BG -->|"Trigger Opt-In Greeting"| TW1["Twilio WhatsApp API<br/>(+1 415 523 8886)"]
        W3 --> TW2["Customer Messages on WhatsApp"]
        TW1 --> TW2
        TW2 --> WH1["POST /webhooks/whatsapp"]
        WH1 --> AI["Google Gemini AI Engine<br/>(conversation_ai.py)"]
        AI <-->|"Load & Save State"| DB3
        AI -->|"Interactive Questions<br/>(Location, BHK, Budget, Timeline, Payment, Remarks)"| TW2
        AI -->|"Complete Questionnaire"| RECAP["Standardized Recap Message<br/>+ Calendly Booking Link"]
        RECAP --> TW2
    end

    %% Lead Evaluation & Zoho Sync
    subgraph S5["5. AI Lead Qualification & Zoho CRM Integration"]
        AI --> EVAL["AI Lead Intent Evaluator<br/>(Gemini 3.5 Flash Lite)"]
        VAL2 --> EVAL
        EVAL -->|"Lead Score >= 60<br/>High Intent / Immediate"| HOT{"Lead Rating?"}
        HOT -->|"🔥 HOT LEAD"| Z1["Zoho CRM Leads Module<br/>(OAuth v8 Upsert API)"]
        HOT -->|"❄️ WARM / COLD"| DB4
        Z1 -->|"Save Zoho Lead ID"| DB4
    end

    %% Calendly & Admin
    subgraph S6["6. Calendly Booking & Admin Portal"]
        W4 --> CAL["Customer Books 30-Min Slot"]
        CAL --> WH2["POST /webhooks/calendly"]
        WH2 --> DB5
        WH2 -->|"Update Appointment"| Z1
        WH2 -->|"Send WhatsApp Booking Confirmation"| TW1

        ADMIN["CRM Administrator"] --> ADM_PAGE["GET /admin<br/>(admin.html)"]
        ADM_PAGE <-->|"Unified Upsert Leads & Cascade Delete"| DB4
        ADM_PAGE <-->|"Enquiries & Contacts Overview"| DB1
    end

    class V,W1,W2,W3,W4 secondary;
    class EP1,EP2,EP3,VAL1,VAL2,BG,WH1,AI,RECAP primary;
    class DB1,DB2,DB3,DB4,DB5 database;
    class TW1,TW2,Z1,CAL,WH2 external;
    class HOT,EVAL hot;
    class ADMIN,ADM_PAGE accent;
"""
    },

    "workflow_2_contact_whatsapp_ai": {
        "title": "Contact Us Form & WhatsApp AI Chatbot Flow",
        "description": "Step-by-step customer journey from Contact Us form submission to WhatsApp AI qualification and meeting booking.",
        "mermaid": """flowchart TD
    classDef start fill:#f1f5f9,stroke:#64748b,stroke-width:2px,color:#0f172a;
    classDef process fill:#2A9DAE,stroke:#1e7482,stroke-width:2px,color:#ffffff;
    classDef db fill:#ffffff,stroke:#2A9DAE,stroke-width:2px,color:#0f172a;
    classDef decision fill:#fef3c7,stroke:#d97706,stroke-width:2px,color:#92400e;
    classDef success fill:#f0fdf4,stroke:#16a34a,stroke-width:2px,color:#15803d;
    classDef external fill:#fff7ed,stroke:#ea580c,stroke-width:1.5px,color:#9a3412;

    START(["Customer Visits Contact Us Page"]) --> FORM["Customer Fills Form:<br/>• First Name & Last Name<br/>• Email Address<br/>• Phone Number (+91...)<br/>• Initial Requirement<br/>• Checkbox: WhatsApp Opt-In"]
    
    FORM --> SUBMIT["Click 'Submit' Button"]
    SUBMIT --> API["FastAPI: POST /api/contact"]

    API --> VAL{"Pydantic Validation<br/>(E.164 Phone & Email)"}
    VAL -->|"❌ Invalid"| ERR["HTTP 422: Return Helpful Error Message"]
    VAL -->|"✅ Valid"| SAVE["Insert into MongoDB Atlas<br/>('contacts' collection)"]

    SAVE --> OPT{"WhatsApp Opt-in<br/>Checked?"}
    
    OPT -->|"No"| NOTIF_ONLY["Send Salesperson Notification Email<br/>Send Customer Confirmation Email"]
    OPT -->|"Yes"| START_WA["Queue WhatsApp Background Task:<br/>start_questionnaire()"]

    START_WA --> TW_OUT["Twilio API Outbound Send<br/>from +1 415 523 8886"]
    TW_OUT --> PHONE["Customer Receives Notification on WhatsApp Phone"]

    PHONE --> CHAT["Customer Opens Chat & Replies 'Hi' or Message"]
    CHAT --> WEBHOOK["FastAPI: POST /webhooks/whatsapp"]

    WEBHOOK --> ENGINE{"Conversational AI Engine<br/>(conversation_ai.py)"}
    
    subgraph AI_LOOP["Google Gemini 3.5 AI Conversational Loop"]
        ENGINE --> Q_LOC["1. Location Preference<br/>(Haldwani, Nainital, Almora, etc.)"]
        Q_LOC --> Q_BHK["2. Configuration / BHK<br/>(1, 2, 3 BHK, Plot, Villa, Commercial)"]
        Q_BHK --> Q_BUD["3. Budget Range<br/>(Up to 25L, 25-50L, 50L-1Cr, 1-2Cr, >2Cr)"]
        Q_BUD --> Q_TIME["4. Buying Timeline<br/>(Immediate, 1 Month, 3 Months, 6 Months)"]
        Q_TIME --> Q_PAY["5. Payment Preference<br/>(Home Loan, Full Cash, Down Payment Plan)"]
        Q_PAY --> Q_REM["6. Special Requirements / Remarks<br/>(Parking, Floor, Amenities)"]
    end

    Q_REM --> FINISH["All Core Slots Complete!"]
    FINISH --> RECAP["Send Standardized Recap Message:<br/>✅ Thank you, [Name]! I've noted down all your requirements...<br/>📅 Schedule 1-on-1 Consultation: [Calendly Link]"]

    RECAP --> QUALIFY["AI Lead Quality Analysis<br/>(Hot / Warm / Cold Scoring)"]
    QUALIFY --> SAVE_UPSERT["Save to MongoDB 'upserted_leads'<br/>and sync to Zoho CRM if Hot"]

    class START start;
    class FORM,SUBMIT,API,SAVE,START_WA,WEBHOOK,FINISH,RECAP,QUALIFY,SAVE_UPSERT process;
    class VAL,OPT,ENGINE decision;
    class TW_OUT,PHONE,CHAT external;
    class NOTIF_ONLY,ERR success;
"""
    },

    "workflow_3_property_enquiry": {
        "title": "Property Enquiry Submission & Direct Confirmation Flow",
        "description": "Customer journey from Property Enquiry form with location typeahead to database save, instant WhatsApp recap, and Zoho sync.",
        "mermaid": """flowchart TD
    classDef start fill:#f1f5f9,stroke:#64748b,stroke-width:2px,color:#0f172a;
    classDef process fill:#2A9DAE,stroke:#1e7482,stroke-width:2px,color:#ffffff;
    classDef db fill:#ffffff,stroke:#2A9DAE,stroke-width:2px,color:#0f172a;
    classDef decision fill:#fef3c7,stroke:#d97706,stroke-width:2px,color:#92400e;
    classDef success fill:#f0fdf4,stroke:#16a34a,stroke-width:2px,color:#15803d;
    classDef external fill:#fff7ed,stroke:#ea580c,stroke-width:1.5px,color:#9a3412;

    START(["Customer Visits Property Enquiry Page (/enquiry)"]) --> INPUT["Customer Enters Preferences:<br/>• First & Last Name, Email, Mobile<br/>• Location (Typeahead Search)<br/>• BHK Preference<br/>• Budget Range<br/>• Planning to Buy Timeline<br/>• Payment Option<br/>• Remarks & Specific Needs"]

    INPUT -.->|"Typeahead Search"| LOC_API["GET /api/locations<br/>(Photon / OpenStreetMap API)"]
    LOC_API -.->|"Localities in Uttarakhand"| INPUT

    INPUT --> SUBMIT["Click 'Submit Property Enquiry'"]
    SUBMIT --> API["FastAPI: POST /api/enquiry"]

    API --> VAL{"Pydantic Validation<br/>(PropertyEnquiryForm)"}
    VAL -->|"❌ Error"| ERR["HTTP 422: Return Input Correction Notice"]
    
    VAL -->|"✅ Valid"| PERSIST["Insert Record into MongoDB Atlas<br/>('property_leads' collection)"]
    
    PERSIST --> INIT_CONV["Pre-populate 'whatsapp_conversations':<br/>status='complete', stage='complete',<br/>source='property_enquiry_form'"]

    PERSIST --> BG_TASKS["Launch Background Tasks Queue"]

    subgraph BG["Automated Background Jobs"]
        BG_TASKS --> EMAIL["Send Confirmation Email via SMTP<br/>to Customer & Sales Team"]
        BG_TASKS --> WA_OUT["Send Direct WhatsApp Message to Customer:<br/>format_completion_summary_message()<br/>• Complete Requirements Summary<br/>• Calendly 30-min Booking Link"]
        BG_TASKS --> EVAL["Evaluate Lead Quality Score (0-100)<br/>& Lead Rating (Hot, Warm, Cold)"]
    end

    WA_OUT --> CUSTOMER_PHONE["Customer Receives Detailed WhatsApp Message<br/>with Hand-Picked Notification & Meeting Link"]

    EVAL --> IS_HOT{"Lead Rating == 'Hot'?"}
    IS_HOT -->|"🔥 Yes"| ZOHO_SYNC["Sync Lead Directly to Zoho CRM<br/>(Leads Module via OAuth v8 Upsert)"]
    IS_HOT -->|"❄️ No (Warm/Cold)"| ADMIN_ONLY["Saved in MongoDB Atlas & Admin Dashboard<br/>(Filtered from Zoho CRM)"]

    ZOHO_SYNC --> DB_UPSERT["Upsert to 'upserted_leads' Collection<br/>with zoho_lead_id & sync status"]
    ADMIN_ONLY --> DB_UPSERT

    class START start;
    class INPUT,SUBMIT,API,PERSIST,INIT_CONV,BG_TASKS,EMAIL,WA_OUT,EVAL,DB_UPSERT process;
    class VAL,IS_HOT decision;
    class LOC_API,CUSTOMER_PHONE,ZOHO_SYNC external;
    class ADMIN_ONLY,ERR success;
"""
    },

    "workflow_4_ai_qualification_zoho": {
        "title": "AI Lead Qualification & Zoho CRM Sync Flow",
        "description": "AI-driven lead qualification gatekeeper determining lead temperature and routing hot leads into Zoho CRM.",
        "mermaid": """flowchart TD
    classDef start fill:#f1f5f9,stroke:#64748b,stroke-width:2px,color:#0f172a;
    classDef process fill:#2A9DAE,stroke:#1e7482,stroke-width:2px,color:#ffffff;
    classDef hot fill:#fef2f2,stroke:#dc2626,stroke-width:2px,color:#991b1b;
    classDef warm fill:#fefce8,stroke:#ca8a04,stroke-width:2px,color:#854d0e;
    classDef cold fill:#eff6ff,stroke:#2563eb,stroke-width:2px,color:#1e40af;
    classDef decision fill:#fef3c7,stroke:#d97706,stroke-width:2px,color:#92400e;
    classDef external fill:#fff7ed,stroke:#ea580c,stroke-width:1.5px,color:#9a3412;
    classDef db fill:#ffffff,stroke:#2A9DAE,stroke-width:2px,color:#0f172a;

    START(["New Completed Lead Received<br/>(Website Enquiry or WhatsApp Questionnaire)"]) --> EXTRACT["Extract Criteria Payload:<br/>• Location, BHK, Budget Range<br/>• Buying Timeline & Payment Option<br/>• Specific Requirements & Conversation Transcript"]

    EXTRACT --> AI_ENGINE["Google Gemini 3.5 AI Lead Evaluator<br/>(analyze_lead_with_ai in conversation_ai.py)"]

    subgraph CRITERIA["AI Evaluation Matrix & Intent Scoring"]
        AI_ENGINE --> C1["Urgency: Immediate / 1 Month (+35 pts)"]
        AI_ENGINE --> C2["Budget: > 1 Crore / High Value (+30 pts)"]
        AI_ENGINE --> C3["Financial Readiness: Full Cash / Pre-Approved (+25 pts)"]
        AI_ENGINE --> C4["Engagement: Complete Criteria & Valid Locality (+10 pts)"]
    end

    C1 & C2 & C3 & C4 --> SCORE["Compute Final Score (0 - 100)<br/>& Executive Assessment Summary"]

    SCORE --> GATE{"Intent Classification"}

    GATE -->|"Score >= 60<br/>High Urgency / High Budget"| HOT["🔥 HOT LEAD<br/>(Immediate Purchasing Intent)"]
    GATE -->|"Score 30 - 59<br/>3-6 Months / Moderate Budget"| WARM["⚡ WARM LEAD<br/>(Nurturing Pipeline)"]
    GATE -->|"Score < 30<br/>Just Exploring / Unresponsive"| COLD["❄️ COLD LEAD<br/>(Low Priority Archive)"]

    HOT --> ZOHO_CHECK{"Zoho CRM Configured?"}
    ZOHO_CHECK -->|"Yes"| REFRESH_TOKEN["Refresh Zoho OAuth Token<br/>(POST https://accounts.zoho.in/oauth/v2/token)"]
    REFRESH_TOKEN --> UPSERT_ZOHO["POST https://www.zohoapis.in/crm/v8/Leads/upsert<br/>Payload: First Name, Last Name, Phone, Email,<br/>Property Preferences, Lead Score, Source"]
    
    UPSERT_ZOHO --> ZOHO_OK["Zoho Returns 200/201<br/>Capture 'zoho_lead_id'"]
    
    ZOHO_OK --> SAVE_HOT["Persist in MongoDB 'upserted_leads'<br/>• zoho_sync_status: 'synced'<br/>• zoho_lead_id: Record ID<br/>• lead_rating: 'Hot'"]

    WARM --> SAVE_WARM["Persist in MongoDB 'upserted_leads'<br/>• zoho_sync_status: 'skipped_cold'<br/>• zoho_sync_reason: 'Filtered from Zoho (Hot leads only)'<br/>• lead_rating: 'Warm'"]
    COLD --> SAVE_COLD["Persist in MongoDB 'upserted_leads'<br/>• zoho_sync_status: 'skipped_cold'<br/>• zoho_sync_reason: 'Filtered from Zoho (Hot leads only)'<br/>• lead_rating: 'Cold'"]

    SAVE_HOT --> ADMIN_VIEW["Visible on Admin CRM Dashboard<br/>with 🔥 Hot Lead & Zoho Synced Badges"]
    SAVE_WARM --> ADMIN_VIEW
    SAVE_COLD --> ADMIN_VIEW

    class START start;
    class EXTRACT,AI_ENGINE,SCORE,SAVE_HOT,ADMIN_VIEW process;
    class HOT hot;
    class WARM warm;
    class COLD cold;
    class GATE,ZOHO_CHECK decision;
    class REFRESH_TOKEN,UPSERT_ZOHO,ZOHO_OK external;
    class SAVE_WARM,SAVE_COLD db;
"""
    },

    "workflow_5_calendly_booking": {
        "title": "Calendly Consultation Booking & Reminder Flow",
        "description": "Seamless meeting scheduling workflow via Calendly with HMAC webhook verification and Twilio appointment confirmation.",
        "mermaid": """flowchart TD
    classDef start fill:#f1f5f9,stroke:#64748b,stroke-width:2px,color:#0f172a;
    classDef process fill:#2A9DAE,stroke:#1e7482,stroke-width:2px,color:#ffffff;
    classDef decision fill:#fef3c7,stroke:#d97706,stroke-width:2px,color:#92400e;
    classDef success fill:#f0fdf4,stroke:#16a34a,stroke-width:2px,color:#15803d;
    classDef external fill:#fff7ed,stroke:#ea580c,stroke-width:1.5px,color:#9a3412;
    classDef db fill:#ffffff,stroke:#2A9DAE,stroke-width:2px,color:#0f172a;

    START(["Customer Clicks Calendly Link in WhatsApp / Email<br/>(https://calendly.com/shailendra-profilent/30min)"]) --> CAL_UI["Calendly Booking Page:<br/>• Selects Date & Time Slot (30 Mins)<br/>• Enters Name, Email & Phone Number<br/>• Confirms Appointment"]

    CAL_UI --> CAL_SERVER["Calendly Webhook Triggered<br/>Event: 'invitee.created'"]
    CAL_SERVER --> WEBHOOK["FastAPI: POST /webhooks/calendly"]

    WEBHOOK --> SIG_CHECK{"Verify HMAC-SHA256 Signature<br/>(CALENDLY_WEBHOOK_SIGNING_KEY)"}
    SIG_CHECK -->|"❌ Invalid Signature"| REJECT["HTTP 401: Unauthorized Request"]

    SIG_CHECK -->|"✅ Verified"| PARSE["Extract Booking Metadata:<br/>• Invitee Name, Email, Phone<br/>• Meeting Start & End Time (IST)<br/>• Meeting Location / Join Link<br/>• Reschedule & Cancellation URLs"]

    PARSE --> MATCH_LEAD{"Match Customer Phone<br/>in MongoDB Atlas?"}
    MATCH_LEAD -->|"Found"| LINK_LEAD["Link to existing contact / enquiry record<br/>in 'property_leads' collection"]
    MATCH_LEAD -->|"Not Found"| NEW_LEAD["Create new appointment lead record"]

    LINK_LEAD & NEW_LEAD --> SAVE_APT["Insert record into 'appointments' collection<br/>Status: 'confirmed'"]

    SAVE_APT --> CRM_UPDATE["Update Lead in Zoho CRM:<br/>Add Note: '30-min Consultation Booked'<br/>Update Stage: 'Meeting Scheduled'"]

    SAVE_APT --> TW_CONFIRM["Twilio WhatsApp Outbound Confirmation<br/>to Customer Phone (+1 415 523 8886)"]

    subgraph WA_MSG["Customer WhatsApp Confirmation"]
        TW_CONFIRM --> MSG_CONTENT["Profilent Consultation Confirmed! 📅<br/>• Host: Property Specialist Team<br/>• Date & Time: [Formatted Start Time IST]<br/>• Join Link: [Meeting URL]<br/>• Reschedule Link: [Calendly Reschedule URL]"]
    end

    MSG_CONTENT --> NOTIFY_SALES["Send Sales Notification Email via SMTP<br/>to Sales Rep with Full Meeting Details"]

    class START start;
    class CAL_UI,CAL_SERVER,TW_CONFIRM external;
    class WEBHOOK,PARSE,LINK_LEAD,NEW_LEAD,SAVE_APT,CRM_UPDATE,NOTIFY_SALES process;
    class SIG_CHECK,MATCH_LEAD decision;
    class REJECT,MSG_CONTENT success;
"""
    },

    "workflow_6_admin_crm_upsert": {
        "title": "Unified Upsert Leads & Admin CRM Dashboard Flow",
        "description": "Comprehensive administrative control panel: deduplicated leads, live search, single updated requirement, and cascading delete.",
        "mermaid": """flowchart TD
    classDef start fill:#f1f5f9,stroke:#64748b,stroke-width:2px,color:#0f172a;
    classDef process fill:#2A9DAE,stroke:#1e7482,stroke-width:2px,color:#ffffff;
    classDef db fill:#ffffff,stroke:#2A9DAE,stroke-width:2px,color:#0f172a;
    classDef decision fill:#fef3c7,stroke:#d97706,stroke-width:2px,color:#92400e;
    classDef hot fill:#fef2f2,stroke:#dc2626,stroke-width:2px,color:#991b1b;
    classDef admin fill:#e0f2fe,stroke:#0284c7,stroke-width:2px,color:#0369a1;

    ADMIN(["Property Administrator"]) --> LOGIN["Navigate to /admin (Login Page)"]
    LOGIN --> AUTH{"Verify Credentials<br/>(Session Middleware)"}
    AUTH -->|"Invalid"| LOGIN_ERR["Show Authentication Error"]
    
    AUTH -->|"Valid"| DASH["Admin CRM Dashboard (admin.html)"]

    subgraph VIEWS["Admin Dashboard Views & Navigation"]
        DASH --> V_OVERVIEW["CRM Overview:<br/>• Today's Enquiries & Total Leads<br/>• BHK Preference Donut Chart<br/>• Latest Contact Us Submissions"]
        DASH --> V_ALL["All Leads View:<br/>Tabular list of all raw submissions"]
        DASH --> V_UPSERT["★ Upsert Leads View (#upsert):<br/>Deduplicated unified customer view"]
        DASH --> V_CONTACT["Contact Us Leads View"]
        DASH --> V_ENQ["Property Enquiries View"]
    end

    subgraph UPSERT_LOGIC["Unified Leads Processing Engine (/api/admin/upsert-leads)"]
        V_UPSERT --> FETCH["Fetch raw 'contacts' and 'property_leads'"]
        FETCH --> DEDUP["Deduplicate & Unify by:<br/>• Normalized 10-Digit Phone Number<br/>• Lowercase Email Address"]
        DEDUP --> BADGES["Compute Source Badges:<br/>'Contact Us', 'Property Enquiry', 'X Submissions'"]
        DEDUP --> REQ_RULE["Requirements Rule:<br/>Display ONLY the latest updated requirement<br/>(Full history available in hover tooltip)"]
        DEDUP --> ZOHO_BADGE["Assign Quality / Zoho Status Badge:<br/>🔥 Hot Lead (Synced with Zoho ID)<br/>❄️ Saved in Admin (Filtered from Zoho)"]
        DEDUP --> SAVE_COL["Synchronize to MongoDB Atlas<br/>'upserted_leads' collection"]
    end

    subgraph ADMIN_OPS["Administrative Actions"]
        V_UPSERT --> SEARCH["Live Search & Instant Filtering<br/>(Filter by Name, Phone, Email, Preferences)"]
        V_UPSERT --> HORIZ_SCROLL["Header Navigation & Floating Edge Scroll Arrows<br/>(Smooth horizontal table scrolling)"]
        V_UPSERT --> BATCH_DEL["Select Leads via Checkboxes<br/>Click 'Delete Lead'"]
        BATCH_DEL --> CASCADE_DEL["Cascading Delete Operation:<br/>POST /api/admin/leads/batch-delete<br/>Removes record from 'upserted_leads' AND<br/>all underlying 'contacts' & 'property_leads'"]
        V_UPSERT --> RESYNC["Trigger Zoho CRM Resync<br/>(Auto background worker polls every 15s)"]
    end

    class ADMIN admin;
    class LOGIN,DASH,V_OVERVIEW,V_ALL,V_UPSERT,V_CONTACT,V_ENQ process;
    class AUTH decision;
    class FETCH,DEDUP,BADGES,REQ_RULE,ZOHO_BADGE,SAVE_COL db;
    class SEARCH,HORIZ_SCROLL,BATCH_DEL,CASCADE_DEL,RESYNC hot;
"""
    }
}


def render_and_save_diagrams():
    print("=" * 80)
    print("PROFILENT - WORKFLOW DIAGRAM PNG GENERATOR")
    print("=" * 80)

    for key, wf in WORKFLOWS.items():
        title = wf["title"]
        mermaid_code = wf["mermaid"].strip()
        filename = f"{key}.png"
        img_dest = IMAGE_DIR / filename
        static_dest = STATIC_DIR / filename
        mmd_dest = STATIC_DIR / f"{key}.mmd"

        print(f"\n[+] Processing: {title}")
        print(f"    File: {filename}")

        # Save raw mermaid syntax for reference
        with open(mmd_dest, "w", encoding="utf-8") as f:
            f.write(mermaid_code)

        # Generate base64 url
        b64 = base64.urlsafe_b64encode(mermaid_code.encode("utf-8")).decode("ascii")
        url = f"https://mermaid.ink/img/{b64}?width=1800&bgColor=white"

        try:
            resp = requests.get(url, timeout=25)
            if resp.status_code == 200 and len(resp.content) > 1000:
                with open(img_dest, "wb") as f:
                    f.write(resp.content)
                with open(static_dest, "wb") as f:
                    f.write(resp.content)
                print(f"    -> Successfully generated PNG ({len(resp.content)} bytes)")
                print(f"       Saved to: {img_dest}")
                print(f"       Saved to: {static_dest}")
            else:
                print(f"    [!] Warning: Rendering returned HTTP {resp.status_code} ({len(resp.content)} bytes)")
        except Exception as e:
            print(f"    [!] Error generating {filename}: {e}")

    print("\n" + "=" * 80)
    print("ALL WORKFLOW PNG DIAGRAMS GENERATED SUCCESSFULLY!")
    print("=" * 80)


if __name__ == "__main__":
    render_and_save_diagrams()
