"""MongoDB client factory and collection accessors.

Owner: Member 1 (Data & MongoDB)
Provides type-safe collection getters and connection verification.
"""
from __future__ import annotations

from typing import Any, Optional

from pymongo import MongoClient
from pymongo.collection import Collection
from pymongo.database import Database
from pymongo.errors import PyMongoError

from anvesaka_AI.config import settings
from anvesaka_AI.schemas import COLLECTIONS, create_indexes

_client_cache: Optional[MongoClient] = None


def get_client(uri: Optional[str] = None, timeout_ms: int = 5000) -> MongoClient:
    """Return a thread-safe PyMongo MongoClient instance."""
    global _client_cache
    target_uri = uri or settings.mongo_uri
    if _client_cache is None:
        _client_cache = MongoClient(target_uri, serverSelectionTimeoutMS=timeout_ms)
    return _client_cache



def get_db(db_name: Optional[str] = None) -> Database:
    """Return the application database."""
    client = get_client()
    return client[db_name or settings.mongo_db]


def get_collection(coll_name: str) -> Collection:
    """Return a collection by name."""
    db = get_db()
    return db[coll_name]


def get_alerts_collection() -> Collection:
    """Return the 'alerts' collection."""
    return get_collection("alerts")


def get_playbook_collection() -> Collection:
    """Return the 'playbook' collection."""
    return get_collection("playbook")


def get_nodes_collection() -> Collection:
    """Return the 'nodes' (CMDB) collection."""
    return get_collection("nodes")


def get_triage_runs_collection() -> Collection:
    """Return the 'triage_runs' audit log collection."""
    return get_collection("triage_runs")


def get_eval_runs_collection() -> Collection:
    """Return the 'eval_runs' benchmark collection."""
    return get_collection("eval_runs")


def ping_db() -> bool:
    """Check whether MongoDB is reachable."""
    ok, _ = check_db_connection()
    return ok


def check_db_connection() -> tuple[bool, str]:
    """Test connection and return status plus descriptive message/error."""
    try:
        client = get_client()
        client.admin.command("ping")
        return True, "Connected successfully"
    except (PyMongoError, Exception) as e:
        return False, str(e)



def ensure_indexes() -> bool:
    """Create all required compound and text indexes defined in schemas.py."""
    try:
        db = get_db()
        create_indexes(db)
        return True
    except (PyMongoError, Exception):
        return False
