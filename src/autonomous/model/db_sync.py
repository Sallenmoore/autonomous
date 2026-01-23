import os
import urllib
from datetime import datetime

import numpy as np
import pymongo
import redis
import requests
from redis.commands.search.field import TagField, TextField, VectorField
from redis.commands.search.index_definition import IndexDefinition, IndexType

# CONFIGURATION
db_host = os.getenv("DB_HOST", "db")
db_port = os.getenv("DB_PORT", 27017)
password = urllib.parse.quote_plus(str(os.getenv("DB_PASSWORD")))
username = urllib.parse.quote_plus(str(os.getenv("DB_USERNAME")))
MEDIA_URL = "http://media_ai_internal:5005"
REDIS_HOST = os.getenv("REDIS_HOST", "cachedb")
MONGO_URI = f"mongodb://{username}:{password}@{db_host}:{db_port}/?authSource=admin"

# DB SETUP
r = redis.Redis(host=REDIS_HOST, port=6379, decode_responses=True)

mongo = pymongo.MongoClient(MONGO_URI)
db = mongo[os.getenv("DB_DB")]
# connect(host=f"mongodb://{username}:{password}@{host}:{port}/{dbname}?authSource=admin")


def get_vector(text):
    """Helper to get embedding from your Media AI container"""
    try:
        resp = requests.post(f"{MEDIA_URL}/embeddings", json={"text": text}, timeout=5)
        if resp.status_code == 200:
            return resp.json()["embedding"]
    except Exception as e:
        print(f"Vector Gen Failed: {e}")
    return None


# UPDATE THIS FUNCTION
def process_single_object_sync(object_id, collection_name):
    """
    Worker now requires collection_name to know where to look.
    """
    print(f"Processing Sync for: {object_id} in {collection_name}")

    from bson.objectid import ObjectId

    # FIX: Use dynamic collection access instead of db.objects
    try:
        # Tries to convert string ID to ObjectId.
        # If your DB uses String IDs, remove the ObjectId() wrapper.
        oid = ObjectId(object_id)
        doc = db[collection_name].find_one({"_id": oid})
    except Exception:
        # Fallback if ID is not a valid ObjectId string
        doc = db[collection_name].find_one({"_id": object_id})

    if not doc:
        print(f"Object {object_id} not found in collection '{collection_name}'")
        # Optional: Remove from Redis index if it exists
        r.delete(f"lore:{object_id}")
        return

    # 2. Construct Searchable Text
    # (Existing logic...)
    searchable_text = (
        f"{doc.get('name', '')}: {doc.get('description', '')} {doc.get('history', '')}"
    )

    if len(searchable_text) < 10:
        return

    # 3. Generate Vector
    vector = get_vector(searchable_text)

    # 4. Save to Redis Index
    if vector:
        r.hset(
            f"lore:{object_id}",
            mapping={
                "mongo_id": str(object_id),
                "collection": collection_name,  # Useful for debugging
                "content": searchable_text,
                "vector": np.array(vector, dtype=np.float32).tobytes(),
                "last_synced": datetime.utcnow().isoformat(),
            },
        )
        print(f"Successfully Indexed: {doc.get('name')}")


# UPDATE THIS FUNCTION
def request_indexing(object_id, collection_name):
    """
    Trigger now requires collection_name.
    """
    str_id = str(object_id)
    # Include collection in key to avoid collisions between 'User:123' and 'World:123'
    cooldown_key = f"sync_cooldown:{collection_name}:{str_id}"

    if r.exists(cooldown_key):
        print(f"Skipping sync for {str_id}: Updated less than 10 mins ago.")
        return False

    r.set(cooldown_key, "1", ex=600)

    try:
        # PASS THE COLLECTION NAME HERE
        process_single_object_sync(str_id, collection_name)
        return True
    except Exception as e:
        print(f"Sync failed: {e}")
        r.delete(cooldown_key)
        return False
