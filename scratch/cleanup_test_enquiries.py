import os
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv()
uri = os.getenv("MONGODB_URI")
db_name = os.getenv("DB_NAME", "property_db")

client = MongoClient(uri, serverSelectionTimeoutMS=10000)
db = client[db_name]

# Delete test entries
r1 = db.enquiries.delete_many({"email": {"$in": ["deepak.rawat@example.in", "sunita.pant@example.in"]}})
r2 = db.property_leads.delete_many({"email": {"$in": ["deepak.rawat@example.in", "sunita.pant@example.in"]}})
r3 = db.contacts.delete_many({"email": {"$in": ["deepak.rawat@example.in", "sunita.pant@example.in"]}})
print(f"Cleaned up {r1.deleted_count + r2.deleted_count + r3.deleted_count} test documents from database.")

