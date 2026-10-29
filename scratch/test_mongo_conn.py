import os
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv()
uri = os.getenv("MONGODB_URI")
db_name = os.getenv("DB_NAME", "property_db")

print("Testing MongoDB connection to db:", db_name)
try:
    client = MongoClient(uri, serverSelectionTimeoutMS=4000)
    db = client[db_name]
    c_count = db.contacts.count_documents({})
    p_count = db.property_leads.count_documents({})
    print(f"Connection SUCCESS! contacts count: {c_count}, property_leads count: {p_count}")
except Exception as e:
    print(f"Connection FAILED: {type(e).__name__}: {e}")

