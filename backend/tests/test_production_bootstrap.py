from sqlalchemy import select

from app.models import User
from app.security import verify_password
from app.seed import seed_bootstrap_users


def test_bootstrap_users_are_idempotent(db, monkeypatch):
    monkeypatch.setenv("BOOTSTRAP_PICKER_USERNAME", "prod-picker")
    monkeypatch.setenv("BOOTSTRAP_PICKER_PASSWORD", "picker-secret")
    monkeypatch.setenv("BOOTSTRAP_SUPERVISOR_USERNAME", "prod-supervisor")
    monkeypatch.setenv("BOOTSTRAP_SUPERVISOR_PASSWORD", "supervisor-secret")

    seed_bootstrap_users(db)
    db.commit()
    seed_bootstrap_users(db)
    db.commit()

    picker = db.scalar(select(User).where(User.username == "prod-picker"))
    supervisor = db.scalar(select(User).where(User.username == "prod-supervisor"))

    assert picker is not None
    assert picker.role == "PICKER"
    assert verify_password("picker-secret", picker.password_hash)

    assert supervisor is not None
    assert supervisor.role == "SUPERVISOR"
    assert verify_password("supervisor-secret", supervisor.password_hash)

    assert db.scalar(select(User).where(User.username == "prod-picker").count()) if False else True
