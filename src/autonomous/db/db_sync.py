import os
import time
import urllib.parse
import uuid
from datetime import datetime

import bson
import pymongo
import redis
import requests

from autonomous import log
from autonomous.taskrunner.autotasks import AutoTasks, TaskPriority

_redis_client = None
_mongo_client = None
_mongo_db = None


def _get_redis():
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.Redis(
            host=os.getenv("REDIS_HOST", "cachedb"),
            port=int(os.getenv("REDIS_PORT", 6379)),
            decode_responses=True,
        )
    return _redis_client


def _get_mongo_db():
    global _mongo_client, _mongo_db
    if _mongo_db is None:
        password = urllib.parse.quote_plus(str(os.getenv("DB_PASSWORD")))
        username = urllib.parse.quote_plus(str(os.getenv("DB_USERNAME")))
        host = os.getenv("DB_HOST", "db")
        port = os.getenv("DB_PORT", 27017)
        uri = f"mongodb://{username}:{password}@{host}:{port}/?authSource=admin"
        _mongo_client = pymongo.MongoClient(uri)
        _mongo_db = _mongo_client[os.getenv("DB_DB")]
    return _mongo_db


def _media_url() -> str:
    return os.getenv("MEDIA_API_BASE_URL", "http://media_ai:5005")


def _get_vector_local(text):
    """Legacy media_ai HTTP path — preserved as the local-provider fallback."""
    try:
        resp = requests.post(
            f"{_media_url()}/embeddings", json={"text": text}, timeout=30
        )
        if resp.status_code == 200:
            return resp.json()["embedding"]
    except (requests.RequestException, ValueError, KeyError) as e:
        print(f"Vector Gen Failed: {e}")
    return None


def _get_vector_openai(text):
    """OpenAI-compatible HPC path. __new__ bypass keeps Mongo out of the
    RQ worker — `get_embedding` only reads class-level config."""
    from autonomous.ai.models.openai_compat import OpenAIClient

    client = OpenAIClient.__new__(OpenAIClient)
    try:
        return client.get_embedding(text)
    except Exception as e:
        # Failure here means RAG goes context-free for this save; that's
        # noisy but recoverable, and the caller already tolerates None.
        print(f"Vector Gen (HPC) Failed: {e}")
        return None


def _get_vector_mock(text):
    """Deterministic stub for tests. Matches MockAIModel.get_embedding."""
    return [1.0] + [0.0] * 383


_VECTOR_PROVIDERS = {
    "local": _get_vector_local,
    "openai": _get_vector_openai,
    "mock": _get_vector_mock,
}


def get_vector(text):
    """
    Returns an embedding vector for ``text`` using the provider selected
    by ``EMBEDDING_AI_AGENT`` (default ``local``).

    Returns None on failure so callers can degrade gracefully — the RAG
    layer treats a missing vector as "skip indexing this save".
    """
    provider = os.getenv("EMBEDDING_AI_AGENT", "local")
    fn = _VECTOR_PROVIDERS.get(provider, _get_vector_local)
    return fn(text)


def process_single_object_sync(object_id, collection_name, token):
    """
    THE WORKER FUNCTION (Runs in Background).
    It is safe to sleep here because we are not in the web request.
    """
    str_id = str(object_id)
    token_key = f"sync_token:{collection_name}:{str_id}"
    r = _get_redis()
    db = _get_mongo_db()

    # 1. THE DEBOUNCE WAIT (Happens in background)
    time.sleep(5)

    # 2. THE VERIFICATION
    # Check if a newer save happened while we slept
    current_active_token = r.get(token_key)

    if current_active_token != token:
        print(f"Skipping sync for {str_id}: Superseded by a newer save.")
        return

    # 3. THE EXECUTION (Embedding generation)
    from bson.objectid import ObjectId

    try:
        oid = ObjectId(object_id)
        doc = db[collection_name].find_one({"_id": oid})
    except (bson.errors.InvalidId, TypeError):
        doc = db[collection_name].find_one({"_id": object_id})

    if not doc:
        print(f"Object {object_id} not found in collection '{collection_name}'")
        r.delete(f"{collection_name}:{object_id}")
        return

    # 2. Construct Searchable Text
    # (Existing logic...)
    log(doc.get("associations"))
    searchable_text = (
        f"{doc.get('name', '')}: {doc.get('history', '')}"
        f"Related: {', '.join([str(a) for a in doc['associations'][:20]]) if doc.get('associations') else ''}"
    )

    if len(searchable_text) < 10:
        return

    # 3. Generate Vector
    vector = get_vector(searchable_text)

    # 4. Save to Redis Index
    if vector:
        # numpy is only needed when actually writing a vector — keep it
        # out of the autonomous.db import-time graph so consumers that
        # don't use vector embeddings (most ORM usage) can install
        # without it.
        import numpy as np
        _get_redis().hset(
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
    _get_redis().set(token_key, current_token, ex=300)

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
    except (redis.RedisError, ConnectionError) as e:
        print(f"Sync Enqueue failed: {e}")
        return False
