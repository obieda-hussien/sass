from __future__ import annotations

import os
from datetime import datetime, timezone
from threading import Lock
from typing import Any

from pymongo import MongoClient
from pymongo.errors import PyMongoError

_client: MongoClient | None = None
_lock = Lock()


def _db():
    global _client
    uri = os.getenv("MONGODB_URI", "").strip()
    if not uri:
        return None

    if _client is None:
        with _lock:
            if _client is None:
                # Vercel is serverless and bursty: keep pools small, allow warm
                # invocation reuse, and release idle sockets quickly.
                _client = MongoClient(
                    uri,
                    appname="FulfillOS",
                    minPoolSize=0,
                    maxPoolSize=5,
                    maxIdleTimeMS=30_000,
                    connectTimeoutMS=5_000,
                    serverSelectionTimeoutMS=5_000,
                    socketTimeoutMS=10_000,
                    retryWrites=True,
                )
    return _client[os.getenv("MONGODB_DATABASE", "fulfillos_telemetry")]


def emit(collection: str, document: dict[str, Any]) -> bool:
    database = _db()
    if database is None:
        return False
    payload = dict(document)
    payload.setdefault("occurred_at", datetime.now(timezone.utc))
    payload.setdefault("schema_version", 1)
    try:
        database[collection].insert_one(payload)
        return True
    except PyMongoError:
        # Telemetry must never break the warehouse transaction path.
        return False


def ping() -> bool:
    database = _db()
    if database is None:
        return False
    try:
        database.command("ping")
        return True
    except PyMongoError:
        return False
