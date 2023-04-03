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


def get_instance():
    """Get the database instance."""
    return os.genenv("DATABASE", default="LOCAL")
