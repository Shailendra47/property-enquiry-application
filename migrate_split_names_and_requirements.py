"""Migration script to backfill first_name, last_name, full_name, and requirement
across all documents in MongoDB Atlas collections:
1. contacts
2. property_leads
3. whatsapp_conversations
"""

import os
import sys
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv()

uri = os.getenv("MONGODB_URI")
db_name = os.getenv("DB_NAME", "property_db")

if not uri:
    print("ERROR: MONGODB_URI not found in environment.")
    sys.exit(1)

print(f"Connecting to MongoDB Atlas database: {db_name}...")
client = MongoClient(uri, serverSelectionTimeoutMS=10000)
db = client[db_name]

def split_name(full: str) -> tuple[str, str]:
    parts = (full or "").strip().split(maxsplit=1)
    if not parts:
        return ("", "")
    if len(parts) == 1:
        return (parts[0], "")
    return (parts[0], parts[1])

# ----------------------------------------------------
# 1. Migrate contacts collection
# ----------------------------------------------------
print("\n" + "=" * 60)
print("1. Migrating collection: contacts")
print("=" * 60)

contacts_cursor = db.contacts.find({})
c_total = 0
c_updated = 0

for doc in contacts_cursor:
    c_total += 1
    doc_id = doc["_id"]
    existing_first = str(doc.get("first_name") or "").strip()
    existing_last = str(doc.get("last_name") or "").strip()
    existing_full = str(doc.get("full_name") or "").strip()
    existing_req = str(doc.get("requirement") or "").strip()

    # Determine first_name, last_name, full_name
    if not existing_first and existing_full:
        first_name, last_name = split_name(existing_full)
    else:
        first_name = existing_first
        last_name = existing_last

    if not existing_full and (first_name or last_name):
        full_name = f"{first_name} {last_name}".strip()
    else:
        full_name = existing_full

    update_fields = {
        "first_name": first_name,
        "last_name": last_name,
        "full_name": full_name,
        "requirement": existing_req,
    }

    # Only update if fields changed or missing
    if (
        doc.get("first_name") != first_name
        or doc.get("last_name") != last_name
        or doc.get("full_name") != full_name
        or "requirement" not in doc
    ):
        db.contacts.update_one({"_id": doc_id}, {"$set": update_fields})
        c_updated += 1

print(f"Contacts migration complete: {c_updated}/{c_total} documents updated.")


# ----------------------------------------------------
# 2. Migrate property_leads collection
# ----------------------------------------------------
print("\n" + "=" * 60)
print("2. Migrating collection: property_leads")
print("=" * 60)

leads_cursor = db.property_leads.find({})
p_total = 0
p_updated = 0

for doc in leads_cursor:
    p_total += 1
    doc_id = doc["_id"]
    existing_first = str(doc.get("first_name") or "").strip()
    existing_last = str(doc.get("last_name") or "").strip()
    existing_full = str(doc.get("full_name") or "").strip()
    existing_req = str(
        doc.get("requirement")
        or doc.get("remarks_requirements")
        or doc.get("remarks")
        or ""
    ).strip()

    if not existing_first and existing_full:
        first_name, last_name = split_name(existing_full)
    else:
        first_name = existing_first
        last_name = existing_last

    if not existing_full and (first_name or last_name):
        full_name = f"{first_name} {last_name}".strip()
    else:
        full_name = existing_full

    update_fields = {
        "first_name": first_name,
        "last_name": last_name,
        "full_name": full_name,
        "requirement": existing_req,
        "remarks_requirements": existing_req,
    }

    if (
        doc.get("first_name") != first_name
        or doc.get("last_name") != last_name
        or doc.get("full_name") != full_name
        or doc.get("requirement") != existing_req
        or doc.get("remarks_requirements") != existing_req
    ):
        db.property_leads.update_one({"_id": doc_id}, {"$set": update_fields})
        p_updated += 1

print(f"Property Leads migration complete: {p_updated}/{p_total} documents updated.")


# ----------------------------------------------------
# 3. Migrate whatsapp_conversations collection
# ----------------------------------------------------
print("\n" + "=" * 60)
print("3. Migrating collection: whatsapp_conversations")
print("=" * 60)

wa_cursor = db.whatsapp_conversations.find({"whatsapp_answers": {"$exists": True, "$ne": None}})
wa_total = 0
wa_updated = 0

for doc in wa_cursor:
    wa_total += 1
    doc_id = doc["_id"]
    wa = dict(doc.get("whatsapp_answers") or {})
    w_first = str(wa.get("first_name") or "").strip()
    w_last = str(wa.get("last_name") or "").strip()
    w_full = str(wa.get("full_name") or "").strip()
    w_req = str(wa.get("remarks_requirements") or wa.get("remarks") or wa.get("requirement") or "").strip()

    if not w_first and w_full:
        w_first, w_last = split_name(w_full)
    if not w_full and (w_first or w_last):
        w_full = f"{w_first} {w_last}".strip()

    wa["first_name"] = w_first
    wa["last_name"] = w_last
    wa["full_name"] = w_full
    wa["requirement"] = w_req
    wa["remarks_requirements"] = w_req

    db.whatsapp_conversations.update_one(
        {"_id": doc_id},
        {"$set": {
            "whatsapp_answers": wa,
            "first_name": w_first,
            "last_name": w_last,
            "full_name": w_full,
            "requirement": w_req,
        }}
    )
    wa_updated += 1

print(f"WhatsApp Conversations migration complete: {wa_updated}/{wa_total} documents updated.")

print("\n" + "=" * 60)
print("ALL MIGRATIONS FINISHED SUCCESSFULLY!")
print("=" * 60)

