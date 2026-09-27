from __future__ import annotations

import os
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

from .database import Base, engine
from . import models as _models  # noqa: F401
from . import models_ops as _models_ops  # noqa: F401


BASELINE_REVISION = "20260927_0001"
ADVISORY_LOCK_KEY = 2609270401


def _alembic_config(connection: Connection) -> Config:
    backend_root = Path(__file__).resolve().parents[1]
    config = Config(str(backend_root / "alembic.ini"))
    config.set_main_option("script_location", str(backend_root / "alembic"))
    config.attributes["connection"] = connection
    return config


def _has_table(connection: Connection, table_name: str) -> bool:
    return table_name in set(inspect(connection).get_table_names())


def migrate_schema() -> None:
    """Bring the database to the current Alembic head safely.

    Existing v0.3 installations pre-date Alembic. They are stamped at the
    explicit baseline revision and then upgraded. A genuinely empty database is
    bootstrapped from the current metadata once, stamped at head, and all later
    schema evolution is migration-driven.

    PostgreSQL uses a session advisory lock so concurrent serverless cold starts
    cannot race the schema migration.
    """

    if os.getenv("FULFILLOS_DISABLE_AUTO_MIGRATE", "0") == "1":
        return

    with engine.connect() as connection:
        is_postgres = connection.dialect.name == "postgresql"
        if is_postgres:
            connection.execute(text("SELECT pg_advisory_lock(:key)"), {"key": ADVISORY_LOCK_KEY})
            connection.commit()

        try:
            config = _alembic_config(connection)
            has_version_table = _has_table(connection, "alembic_version")
            has_core_schema = _has_table(connection, "users")

            if not has_core_schema:
                # Fresh installation. Creating the current metadata is faster and
                # less fragile than replaying the historical pre-Alembic SQL
                # dumps, then we stamp the exact current head.
                Base.metadata.create_all(bind=connection)
                connection.commit()
                command.stamp(config, "head")
                connection.commit()
                return

            if not has_version_table:
                # Production existed before Alembic. v0.3 is the verified
                # baseline, so do not re-run its historical DDL.
                command.stamp(config, BASELINE_REVISION)
                connection.commit()

            command.upgrade(config, "head")
            connection.commit()
        finally:
            if is_postgres:
                connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": ADVISORY_LOCK_KEY})
                connection.commit()
