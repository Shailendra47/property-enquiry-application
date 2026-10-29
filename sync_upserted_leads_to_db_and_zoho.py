"""Sync and persist all unified upserted leads into MongoDB database (upserted_leads)
and automatically save qualifying Hot leads into Zoho CRM.
"""

import logging
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from bson import ObjectId
from dotenv import load_dotenv
from pymongo import MongoClient

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

import zoho_crm
from main import build_upserted_leads

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("upsert_sync")

MONGODB_URI = os.getenv("MONGODB_URI", "").strip()
DB_NAME = os.getenv("DB_NAME", "property_db")
COLLECTION_NAME = os.getenv("COLLECTION_NAME", "contacts")
ENQUIRY_COLLECTION_NAME = os.getenv("ENQUIRY_COLLECTION_NAME", "property_leads")
UPSERT_COLLECTION_NAME = os.getenv("UPSERT_COLLECTION_NAME", "upserted_leads")


def run_upsert_database_sync():
    print("=" * 80)
    print("PROFILENT CRM - UPSERTED LEADS DATABASE & ZOHO CRM SYNCHRONIZATION")
    print("=" * 80)

    if not MONGODB_URI:
        print("ERROR: MONGODB_URI is not configured in .env")
        sys.exit(1)

    client = MongoClient(MONGODB_URI)
    db = client[DB_NAME]

    print(f"Connected to MongoDB Database: {DB_NAME}")
    print(f"Contacts Collection        : {COLLECTION_NAME}")
    print(f"Enquiry Collection         : {ENQUIRY_COLLECTION_NAME}")
    print(f"Upserted Leads Collection   : {UPSERT_COLLECTION_NAME}")
    print("-" * 80)

    # 1. Ensure indexes on upserted_leads collection
    upsert_col = db[UPSERT_COLLECTION_NAME]
    upsert_col.create_index("id", unique=True)
    upsert_col.create_index("phone")
    upsert_col.create_index("email")
    upsert_col.create_index([("created_at", -1)])
    upsert_col.create_index("lead_rating")
    upsert_col.create_index("zoho_sync_status")
    upsert_col.create_index("zoho_lead_id")

    # 2. Fetch all raw contacts and property enquiries
    contacts_docs = list(db[COLLECTION_NAME].find())
    enquiries_docs = list(db[ENQUIRY_COLLECTION_NAME].find())

    # Format documents with string IDs for builder
    contacts = []
    for c in contacts_docs:
        c_copy = dict(c)
        c_copy["id"] = str(c.get("_id", ""))
        contacts.append(c_copy)

    enquiries = []
    for e in enquiries_docs:
        e_copy = dict(e)
        e_copy["id"] = str(e.get("_id", ""))
        enquiries.append(e_copy)

    print(f"Fetched {len(contacts)} contacts and {len(enquiries)} property enquiries.")

    # 3. Deduplicate & unify into upserted leads
    upserted_leads = build_upserted_leads(contacts, enquiries)
    print(f"Generated {len(upserted_leads)} deduplicated unified lead records.")
    print("-" * 80)

    now = datetime.now(timezone.utc)
    zoho_ready = zoho_crm.zoho_is_configured()

    synced_hot = []
    already_synced = []
    saved_admin_only = []
    errors = []

    for idx, lead in enumerate(upserted_leads, 1):
        lead_id = lead["id"]
        full_name = lead.get("full_name") or f"{lead.get('first_name', '')} {lead.get('last_name', '')}".strip() or "Unnamed"
        ident = lead.get("email") or lead.get("phone") or lead_id
        is_hot = (lead.get("lead_rating") == "Hot")

        # Preserve existing zoho_lead_id from database if already present
        existing = upsert_col.find_one({"id": lead_id})
        if existing and existing.get("zoho_lead_id") and not lead.get("zoho_lead_id"):
            lead["zoho_lead_id"] = existing["zoho_lead_id"]
            lead["zoho_sync_status"] = "synced"
            lead["zoho_synced_at"] = existing.get("zoho_synced_at", now)

        # Check if already synced in Zoho
        if is_hot and lead.get("zoho_lead_id"):
            already_synced.append({
                "id": lead_id,
                "name": full_name,
                "ident": ident,
                "zoho_id": lead["zoho_lead_id"],
                "score": lead.get("lead_score", 0),
            })
        elif is_hot and zoho_ready:
            # Sync to Zoho CRM
            try:
                sources_str = ", ".join(lead.get("sources", ["Unified"]))
                zoho_payload = {
                    **lead,
                    "local_id": lead_id,
                    "mobile_number": lead.get("phone", ""),
                    "source": f"Upserted Lead ({sources_str})",
                }
                zoho_id = zoho_crm.sync_zoho_lead(zoho_payload, only_hot=True)
                if zoho_id:
                    lead["zoho_lead_id"] = zoho_id
                    lead["zoho_sync_status"] = "synced"
                    lead["zoho_synced_at"] = now
                    lead["zoho_sync_reason"] = f"Hot Lead synced to Zoho CRM (Score: {lead.get('lead_score', 0)}/100)"
                    synced_hot.append({
                        "id": lead_id,
                        "name": full_name,
                        "ident": ident,
                        "zoho_id": zoho_id,
                        "score": lead.get("lead_score", 0),
                    })
                else:
                    errors.append({"id": lead_id, "name": full_name, "ident": ident, "error": "Zoho sync returned None"})
            except Exception as e:
                errors.append({"id": lead_id, "name": full_name, "ident": ident, "error": str(e)})
        else:
            saved_admin_only.append({
                "id": lead_id,
                "name": full_name,
                "ident": ident,
                "rating": lead.get("lead_rating", "Cold"),
                "score": lead.get("lead_score", 0),
            })

        # 4. Save to upserted_leads database collection
        lead_doc_to_save = {
            **lead,
            "updated_at": now,
        }
        upsert_col.update_one(
            {"id": lead_id},
            {"$set": lead_doc_to_save},
            upsert=True
        )

        # 5. Propagate Zoho status back to underlying records
        if lead.get("zoho_lead_id"):
            update_sub = {
                "$set": {
                    "zoho_lead_id": lead["zoho_lead_id"],
                    "zoho_sync_status": "synced",
                    "zoho_synced_at": lead.get("zoho_synced_at", now),
                    "zoho_sync_reason": lead.get("zoho_sync_reason", "Synced via unified upsert"),
                }
            }
            for rec in lead.get("records", []):
                r_id = rec.get("id")
                r_entity = rec.get("entity")
                if r_id:
                    try:
                        roid = ObjectId(r_id)
                        if r_entity == "contact":
                            db[COLLECTION_NAME].update_one({"_id": roid}, update_sub)
                        elif r_entity == "enquiry":
                            db[ENQUIRY_COLLECTION_NAME].update_one({"_id": roid}, update_sub)
                    except Exception:
                        pass

    print("\n" + "=" * 80)
    print("DATABASE & ZOHO CRM PERSISTENCE SUMMARY")
    print("=" * 80)
    print(f"Total Unified Leads in Database (upserted_leads) : {len(upserted_leads)}")
    print(f"Hot Leads Newly Synced to Zoho CRM              : {len(synced_hot)}")
    print(f"Hot Leads Already Synced to Zoho CRM            : {len(already_synced)}")
    print(f"Warm / Cold Leads Saved in Database Only        : {len(saved_admin_only)}")
    print(f"Failed / Error Attempts                         : {len(errors)}")
    print("=" * 80)

    if synced_hot:
        print("\n[+] Newly Synced Hot Leads to Zoho CRM:")
        for s in synced_hot:
            print(f"  + {s['name']} ({s['ident']}) | Score: {s['score']} -> Zoho ID: {s['zoho_id']}")

    if already_synced:
        print("\n[*] Already Synced Hot Leads in Zoho CRM:")
        for s in already_synced:
            print(f"  * {s['name']} ({s['ident']}) | Score: {s['score']} -> Zoho ID: {s['zoho_id']}")

    if saved_admin_only:
        print("\n[-] Leads Saved in Database (upserted_leads) Only (Filtered from Zoho):")
        for s in saved_admin_only:
            print(f"  - {s['name']} ({s['ident']}) | Rating: {s['rating']} (Score: {s['score']})")

    if errors:
        print("\n[!] Errors during Sync:")
        for e in errors:
            print(f"  ! {e['name']} ({e['ident']}): {e['error']}")

    print("\nSync complete! All upserted leads are now persisted in the MongoDB database collection 'upserted_leads'.")


if __name__ == "__main__":
    run_upsert_database_sync()

