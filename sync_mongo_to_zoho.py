"""Sync all property leads and contacts from MongoDB Atlas to Zoho CRM Leads module."""

import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

import zoho_crm

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("sync_mongo_to_zoho")

def run_sync():
    print("=" * 60)
    print("Starting MongoDB Atlas <-> Zoho CRM Leads Synchronization")
    print("=" * 60)

    if not zoho_crm.zoho_is_configured():
        print("ERROR: Zoho CRM credentials are not configured in .env")
        sys.exit(1)

    print("Zoho CRM OAuth is verified.")
    print(f"Company: {zoho_crm._get_config()['company']}")
    print(f"Module: {zoho_crm._get_config()['module']}")
    print("-" * 60)

    result = zoho_crm.sync_all_from_mongo()

    print("\n" + "=" * 60)
    print(f"Sync Complete!")
    print(f"Total Successfully Synced: {result.get('total_synced', 0)}")
    print(f"Total Failed: {result.get('total_failed', 0)}")
    print("=" * 60)

    for item in result.get("synced", []):
        print(f"  [OK] {item['type']} {item['ident']} -> Zoho Lead ID: {item['zoho_id']}")

    for item in result.get("failed", []):
        print(f"  [FAIL] {item['type']} {item['ident']}")

if __name__ == "__main__":
    run_sync()

