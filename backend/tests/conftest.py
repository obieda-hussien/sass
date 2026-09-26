from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


TEST_DB = Path(__file__).with_name("test.db")
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB}"

from app.config import get_settings  # noqa: E402
get_settings.cache_clear()

from app.database import Base, engine  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(autouse=True)
def reset_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(scope="session", autouse=True)
def cleanup():
    yield
    if TEST_DB.exists():
        TEST_DB.unlink()
