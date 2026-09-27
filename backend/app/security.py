from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Device, SessionToken, User

ACCESS_MINUTES = int(os.getenv("ACCESS_TOKEN_MINUTES", "30"))
REFRESH_DAYS = int(os.getenv("REFRESH_TOKEN_DAYS", "14"))
PBKDF2_ITERATIONS = 240_000

def _utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iterations, salt_hex, hash_hex = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex), int(iterations))
        return hmac.compare_digest(dk.hex(), hash_hex)
    except Exception:
        return False


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def issue_session(db: Session, user: User, device: Device) -> tuple[str, str, SessionToken]:
    now = datetime.now(timezone.utc)
    access = secrets.token_urlsafe(32)
    refresh = secrets.token_urlsafe(48)
    record = SessionToken(
        user_id=user.id,
        device_id=device.id,
        access_hash=token_hash(access),
        refresh_hash=token_hash(refresh),
        access_expires_at=now + timedelta(minutes=ACCESS_MINUTES),
        refresh_expires_at=now + timedelta(days=REFRESH_DAYS),
    )
    device.last_user_id = user.id
    device.last_seen_at = now
    device.status = "ONLINE"
    db.add(record)
    db.flush()
    return access, refresh, record


def authenticate_access(db: Session, access_token: str) -> tuple[User, Device, SessionToken] | None:
    now = datetime.now(timezone.utc)
    record = db.scalar(select(SessionToken).where(SessionToken.access_hash == token_hash(access_token)))
    if not record or record.revoked or _utc(record.access_expires_at) <= now:
        return None
    user = db.get(User, record.user_id)
    device = db.get(Device, record.device_id)
    if not user or not user.active or not device:
        return None
    return user, device, record


def refresh_session(db: Session, refresh_token: str, device_id: str) -> tuple[str, str, SessionToken] | None:
    now = datetime.now(timezone.utc)
    record = db.scalar(select(SessionToken).where(SessionToken.refresh_hash == token_hash(refresh_token)))
    if not record or record.revoked or _utc(record.refresh_expires_at) <= now or record.device_id != device_id:
        return None
    user = db.get(User, record.user_id)
    device = db.get(Device, device_id)
    if not user or not device or not device.trusted:
        return None
    record.revoked = True
    return issue_session(db, user, device)
