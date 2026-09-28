from fastapi.testclient import TestClient

from app.database import Base, SessionLocal, engine
from app.main import app
from app.seed import seed_demo


def _reset_global_db():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    db = SessionLocal()
    try:
        with db.begin():
            seed_demo(db)
    finally:
        db.close()


def test_first_login_requires_personal_pin_before_warehouse_access():
    _reset_global_db()

    with TestClient(app) as client:
        manager_login = client.post(
            "/auth/login",
            json={
                "username": "supervisor",
                "password": "demo1234",
                "device_id": "WEB-TEST-MANAGER",
                "app_version": "test",
            },
        )
        assert manager_login.status_code == 200
        manager_headers = {
            "Authorization": f"Bearer {manager_login.json()['access_token']}"
        }

        created = client.post(
            "/admin/employees",
            headers=manager_headers,
            json={
                "username": "firstloginpicker",
                "employee_code": "FIRST-001",
                "full_name": "First Login Picker",
                "role": "PICKER",
                "job_title": "Picker",
                "department": "Operations",
            },
        )
        assert created.status_code == 201
        temporary_pin = created.json()["temporary_password"]
        assert temporary_pin.isdigit()
        assert len(temporary_pin) == 6
        assert created.json()["must_change_password"] is True

        login = client.post(
            "/auth/login",
            json={
                "username": "firstloginpicker",
                "password": temporary_pin,
                "device_id": "PDA-FIRST-001",
                "app_version": "0.5.0",
            },
        )
        assert login.status_code == 200
        first_session = login.json()
        assert first_session["must_change_password"] is True
        old_headers = {"Authorization": f"Bearer {first_session['access_token']}"}

        blocked = client.get("/me", headers=old_headers)
        assert blocked.status_code == 428
        assert blocked.json()["detail"]["code"] == "PASSWORD_CHANGE_REQUIRED"

        new_pin = "9" * 7
        changed = client.post(
            "/auth/complete-first-login",
            headers=old_headers,
            json={"new_password": new_pin},
        )
        assert changed.status_code == 200
        session = changed.json()["session"]
        assert session["must_change_password"] is False

        # Session rotation is part of the security boundary.
        assert client.get("/me", headers=old_headers).status_code == 401
        new_headers = {"Authorization": f"Bearer {session['access_token']}"}
        me = client.get("/me", headers=new_headers)
        assert me.status_code == 200
        assert me.json()["username"] == "firstloginpicker"
