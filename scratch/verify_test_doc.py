import os
from bson import ObjectId
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv()
uri = os.getenv("MONGODB_URI")
db_name = os.getenv("DB_NAME", "property_db")

client = MongoClient(uri, serverSelectionTimeoutMS=10000)
db = client[db_name]

doc = db.contacts.find_one({"_id": ObjectId("6ae05ff1095218560058d354")})
print("Retrieved newly created document from MongoDB Atlas:")
for k, v in doc.items():
    print(f"  {k}: {repr(v)}")

# Clean up test documents
db.contacts.delete_one({"_id": ObjectId("6ae05ff1095218560058d354")})
db.contacts.delete_one({"_id": ObjectId("6ae05ff7095218560058d356")})
print("Test documents cleaned up.")

