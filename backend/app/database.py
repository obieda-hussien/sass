from __future__ import annotations

import os
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.pool import StaticPool


def _database_url() -> str:
    url = os.getenv("DATABASE_URL", "sqlite:///./fulfillos.db").strip()
    # Vercel/Neon commonly inject postgresql:// URLs. The project uses psycopg v3,
    # so normalize SQLAlchemy's driver explicitly instead of falling back to psycopg2.
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


DATABASE_URL = _database_url()
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine_kwargs = {
    "future": True,
    "echo": False,
    "connect_args": connect_args,
    "pool_pre_ping": not DATABASE_URL.startswith("sqlite"),
}
if DATABASE_URL in {"sqlite:///:memory:", "sqlite://"}:
    engine_kwargs["poolclass"] = StaticPool

engine = create_engine(DATABASE_URL, **engine_kwargs)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def transaction():
    db = SessionLocal()
    try:
        with db.begin():
            yield db
    finally:
        db.close()
