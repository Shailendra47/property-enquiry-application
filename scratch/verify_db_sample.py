import os
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv()
uri = os.getenv("MONGODB_URI")
db_name = os.getenv("DB_NAME", "property_db")

client = MongoClient(uri, serverSelectionTimeoutMS=10000)
db = client[db_name]

print("=== SAMPLE CONTACT DOC ===")
c = db.contacts.find_one({})
if c:
    print("ID:", c.get("_id"))
    print("First Name:", c.get("first_name"))
    print("Last Name:", c.get("last_name"))
    print("Full Name:", c.get("full_name"))
    print("Requirement:", c.get("requirement"))

print("\n=== SAMPLE PROPERTY LEAD DOC ===")
p = db.property_leads.find_one({})
if p:
    print("ID:", p.get("_id"))
    print("First Name:", p.get("first_name"))
    print("Last Name:", p.get("last_name"))
    print("Full Name:", p.get("full_name"))
    print("Requirement:", p.get("requirement"))
    print("Remarks Requirements:", p.get("remarks_requirements"))

