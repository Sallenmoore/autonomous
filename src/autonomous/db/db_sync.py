import os
import time
import urllib.parse
import uuid
from datetime import datetime

import numpy as np
import pymongo
import redis
import requests

from autonomous.taskrunner.autotasks import AutoTasks, TaskPriority

# CONFIGURATION
db_host = os.getenv("DB_HOST", "db")
db_port = os.getenv("DB_PORT", 27017)
password = urllib.parse.quote_plus(str(os.getenv("DB_PASSWORD")))
username = urllib.parse.quote_plus(str(os.getenv("DB_USERNAME")))
MONGO_URI = f"mongodb://{username}:{password}@{db_host}:{db_port}/?authSource=admin"
MEDIA_URL = os.getenv("MEDIA_API_BASE_URL", "http://media_ai:5005")
REDIS_HOST = os.getenv("REDIS_HOST", "cachedb")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
# DB SETUP
r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
mongo = pymongo.MongoClient(MONGO_URI)
db = mongo[os.getenv("DB_DB")]
# connect(host=f"mongodb://{username}:{password}@{host}:{port}/{dbname}?authSource=admin")


def get_vector(text):
    """Helper to get embedding from your Media AI container"""
    try:
        resp = requests.post(f"{MEDIA_URL}/embeddings", json={"text": text}, timeout=30)
        if resp.status_code == 200:
            return resp.json()["embedding"]
    except Exception as e:
        print(f"Vector Gen Failed: {e}")
    return None


def process_single_object_sync(object_id, collection_name, token):
    """
    THE WORKER FUNCTION (Runs in Background).
    It is safe to sleep here because we are not in the web request.
    """
    str_id = str(object_id)
    token_key = f"sync_token:{collection_name}:{str_id}"

    # 1. THE DEBOUNCE WAIT (Happens in background)
    print(f"Debouncing {str_id} for 5 seconds...")
    time.sleep(5)

    # 2. THE VERIFICATION
    # Check if a newer save happened while we slept
    current_active_token = r.get(token_key)

    if current_active_token != token:
        print(f"Skipping sync for {str_id}: Superseded by a newer save.")
        return

    # 3. THE EXECUTION (Embedding generation)
    print(f"Processing Sync for: {str_id} in {collection_name}")

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


def request_indexing(object_id, collection_name):
    """
    THE TRIGGER FUNCTION (Runs in Main App).
    MUST BE FAST. NO SLEEPING HERE.
    """
    print("Requesting Indexing...")

    # Initialize the Task Runner
    task_runner = AutoTasks()

    str_id = str(object_id)
    token_key = f"sync_token:{collection_name}:{str_id}"

    # 1. GENERATE NEW TOKEN
    current_token = str(uuid.uuid4())

    # 2. SAVE TOKEN TO REDIS (Instant)
    r.set(token_key, current_token, ex=300)

    # 3. ENQUEUE THE TASK (Instant)
    try:
        task_runner.task(
            process_single_object_sync,  # The function to run later
            object_id=str_id,
            collection_name=collection_name,
            token=current_token,
            priority=TaskPriority.LOW,
        )
        return True
    except Exception as e:
        print(f"Sync Enqueue failed: {e}")
        return False
