import os

from .firestore import FirestoreDB
from .local import LocalDB
from .mongo import MongoDB
from .redis import RedisDB

orm = {
    "REDIS": RedisDB,
    "MONGO": MongoDB,
    "LOCAL": LocalDB,
    "FIRESTORE": FirestoreDB,
}


db = orm.get(os.getenv("DATABASE"))  # [db_choice.upper()]()
