"""Sync validated hot leads from MongoDB Atlas to Zoho CRM Leads module."""

import logging
import sys
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

import zoho_crm

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("sync_mongo_to_zoho")


def run_sync():
    print("=" * 70)
    print("Starting MongoDB Atlas -> Zoho CRM Validated Hot Leads Synchronization")
    print("=" * 70)

    if not zoho_crm.zoho_is_configured():
        print("ERROR: Zoho CRM credentials are not configured in .env")
        sys.exit(1)

    config = zoho_crm._get_config()
    print("Zoho CRM OAuth is verified.")
    print(f"Company              : {config['company']}")
    print(f"Module               : {config['module']}")
    print(f"Filter Mode          : ONLY VALIDATED HOT LEADS ({config['only_hot_leads']})")
    print("-" * 70)

    result = zoho_crm.sync_all_from_mongo()

    print("\n" + "=" * 70)
    print("SYNCHRONIZATION SUMMARY")
    print("=" * 70)
    print(f"Total Leads Evaluated : {result.get('total_evaluated', 0)}")
    print(f"Hot Leads Synced      : {result.get('total_synced_hot', 0)} (Sent to Zoho CRM)")
    print(f"Cold Leads Skipped    : {result.get('total_skipped_cold', 0)} (Filtered out)")
    print(f"Invalid Leads Skipped : {result.get('total_skipped_invalid', 0)} (Failed data validation)")
    print(f"Errors / Failed       : {result.get('total_failed', 0)}")
    print("=" * 70)

    if result.get("synced_hot"):
        print("\n[OK] Synced Hot Leads:")
        for item in result["synced_hot"]:
            print(f"  + [{item['type']}] {item['name']} ({item['ident']}) | Score: {item.get('score', 0)} -> Zoho ID: {item['zoho_id']}")

    if result.get("skipped_cold"):
        print("\n[-] Skipped Cold / Inactive Leads:")
        for item in result["skipped_cold"]:
            print(f"  - [{item['type']}] {item['name']} ({item['ident']}) | Rating: {item.get('rating', 'Cold')} (Score: {item.get('score', 0)})")

    if result.get("skipped_invalid"):
        print("\n[!] Skipped Unvalidated / Test Leads:")
        for item in result["skipped_invalid"]:
            err_str = ", ".join(item.get("errors", []))
            print(f"  ! [{item['type']}] {item['name']} ({item['ident']}) -> {err_str}")

    if result.get("failed"):
        print("\n[X] Failed Sync Attempts:")
        for item in result["failed"]:
            print(f"  X [{item['type']}] {item['name']} ({item['ident']})")


if __name__ == "__main__":
    run_sync()
