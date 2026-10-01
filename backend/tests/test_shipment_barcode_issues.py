from datetime import datetime, timezone, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.models import Device, InventoryBalance, InventoryMovement, Product, User
from app.models_ops import ReceivingSession, ShipmentIssue
from app.services.ops_platform import (
    OpsError, adhoc_stow_shipment_item, complete_receiving, create_shipment,
    get_worker_state, open_shipment_receiving, receive_shipment_line,
    report_shipment_issue, set_worker_state, shipment_payload,
)


def setup_shipment(db, label="", qty=3):
    picker = db.scalar(select(User).where(User.username == "picker1"))
    manager = db.scalar(select(User).where(User.username == "supervisor"))
    product = db.scalar(select(Product).where(Product.asin == "DEMO-AMBIENT-001"))
    set_worker_state(db, picker.id, "AVAILABLE", force=True)
    shipment = create_shipment(db, label=label, shipment_type="VENDOR", storage_domain="AMBIENT",
        lines=[{"product_id": product.asin, "expected_qty": qty}], created_by_user_id=manager.id,
        metadata={"supplier_name": "المورد", "purchase_order_ref": "4ZOXV48Q"})
    return picker, product, shipment


def open_session(db, picker, shipment):
    return open_shipment_receiving(db, shipment=shipment, user_id=picker.id,
        device_id="PDA-DEMO-001", opening_temperature_c=22)


def test_generated_codes_are_unique_and_manifest_contains_item_identity(db):
    with db.begin():
        _, product, first = setup_shipment(db)
        _, _, second = setup_shipment(db)
        assert first.label.startswith("IN-") and first.label != second.label
        manifest = shipment_payload(db, first)
        assert manifest["barcode_value"] == first.label
        assert manifest["lines"][0]["title"] == product.title
        assert manifest["lines"][0]["barcode"]
        assert manifest["supplier_name"] == "المورد"


@pytest.mark.parametrize("code", ["ab", "شحنة-١", "BAD CODE", "*BAD*", "A" * 49])
def test_invalid_barcode_codes_rejected(db, code):
    with db.begin(), pytest.raises(OpsError, match="3–48"):
        setup_shipment(db, code)


def test_shared_receiving_rejoin_and_close_release_other_workers(db):
    with db.begin():
        picker, product, shipment = setup_shipment(db, qty=2)
        first = open_session(db, picker, shipment)
        other = User(username="receiver2", password_hash="unused", role="PICKER")
        db.add(other)
        db.flush()
        db.add(Device(id="PDA-SECOND", trusted=True))
        db.flush()
        second = open_shipment_receiving(db, shipment=shipment, user_id=other.id, device_id="PDA-SECOND")
        first_again = open_shipment_receiving(db, shipment=shipment, user_id=picker.id,
            device_id="PDA-SECOND")
        assert first_again.id == first.id and first.device_id == "PDA-SECOND"
        receive_shipment_line(db, shipment=shipment, session=second, event_id="shared",
            product_id=product.id, good_qty=2)
        result = complete_receiving(db, shipment, first)
        assert result["receiving_users"] == []
        assert second.status == "COMPLETED"
        assert get_worker_state(db, other.id).state == "AVAILABLE"
        assert get_worker_state(db, picker.id).state == "STOWING"


def test_break_cannot_be_overwritten_by_opening_shipment(db):
    with db.begin():
        picker, _, shipment = setup_shipment(db)
        set_worker_state(db, picker.id, "BREAK")
        with pytest.raises(OpsError, match="current activity"):
            open_session(db, picker, shipment)
        assert get_worker_state(db, picker.id).state == "BREAK"


def test_planned_direct_stow_needs_no_reason_and_replay_never_counts_twice(db):
    with db.begin():
        picker, product, shipment = setup_shipment(db, qty=2)
        session = open_session(db, picker, shipment)
        args = dict(shipment=shipment, session=session, event_id="planned-direct", product_id=product.id,
            destination_location_id="P-1-A101A110", qty=2, expires_on=datetime.now(timezone.utc).date() + timedelta(days=10),
            lot_code="PLANNED", reason=None)
        first = adhoc_stow_shipment_item(db, **args)
        assert first["shipment"]["received_units"] == first["shipment"]["stowed_units"] == 2
        assert adhoc_stow_shipment_item(db, **args)["duplicate"]
        with pytest.raises(OpsError, match="different contents"):
            adhoc_stow_shipment_item(db, **(args | {"expires_on": datetime.now(timezone.utc).date() + timedelta(days=20)}))
        with pytest.raises(OpsError, match="discrepancy reason"):
            adhoc_stow_shipment_item(db, **(args | {"event_id": "excess-no-reason", "qty": 1}))
        assert shipment.received_units == 2
        assert complete_receiving(db, shipment, session)["status"] == "COMPLETED"


@pytest.mark.parametrize("kind", ["DAMAGED", "EXPIRED"])
def test_rejected_issue_is_audited_and_moves_to_dmg_once(db, kind):
    with db.begin():
        picker, product, shipment = setup_shipment(db)
        open_session(db, picker, shipment)
        args = dict(shipment=shipment, event_id="rejected-issue", product_id=product.id,
            issue_type=kind, qty=2, notes="Incoming units rejected", user_id=picker.id,
            device_id="PDA-DEMO-001", expires_on=datetime.now(timezone.utc).date() - timedelta(days=1))
        first = report_shipment_issue(db, **args)
        assert first["shipment"]["received_units"] == 0
        assert first["shipment"]["damaged_units"] == 2
        assert first["shipment"]["open_issues"] == 1
        assert report_shipment_issue(db, **args)["duplicate"]
        assert len(db.scalars(select(ShipmentIssue)).all()) == 1
        movements = db.scalars(select(InventoryMovement).where(InventoryMovement.reason == "SHIPMENT_DAMAGE")).all()
        assert len(movements) == 1 and movements[0].destination_location_id == "DMG"
        with pytest.raises(OpsError, match="different contents"):
            report_shipment_issue(db, **(args | {"qty": 1}))


def test_wrong_item_report_does_not_receive_stock_and_expired_good_receipt_is_blocked(db):
    with db.begin():
        picker, product, shipment = setup_shipment(db)
        session = open_session(db, picker, shipment)
        report_shipment_issue(db, shipment=shipment, event_id="wrong-item", product_id=product.id,
            issue_type="WRONG_ITEM", qty=1, notes="Not on purchase order", user_id=picker.id, device_id="PDA-DEMO-001")
        assert shipment.received_units == shipment.damaged_units == 0
        with pytest.raises(OpsError, match="expired"):
            receive_shipment_line(db, shipment=shipment, session=session, event_id="expired-good",
                product_id=product.id, good_qty=1, expires_on=datetime.now(timezone.utc).date() - timedelta(days=1))


def test_picker_api_can_lookup_join_leave_report_but_cannot_create_or_resolve(db):
    from app.main import app
    from app.database import get_db
    with db.begin():
        picker, product, shipment = setup_shipment(db, label="4ZOXV48Q")
        shipment_id, product_id = shipment.id, product.id
    app.dependency_overrides[get_db] = lambda: db
    try:
        client = TestClient(app)
        login = client.post("/auth/login", json={"username": "picker1", "password": "demo1234",
            "device_id": "PDA-DEMO-001", "app_version": "0.5.2"})
        assert login.status_code == 200
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        assert client.get("/ops/shipments", headers=headers).status_code == 200
        found = client.get("/ops/shipments/lookup", params={"code": "4zoxv48q"}, headers=headers)
        assert found.status_code == 200 and found.json()["id"] == shipment_id
        assert client.get("/ops/shipments/lookup", params={"code": "UNKNOWN"}, headers=headers).status_code == 404
        assert client.post("/ops/shipments", headers=headers, json={"label": "FORBIDDEN"}).status_code == 403
        assert client.post(f"/ops/shipments/{shipment_id}/open", headers=headers, json={"opening_temperature_c": 20}).status_code == 200
        issue = client.post(f"/ops/shipments/{shipment_id}/issues", headers=headers, json={
            "event_id": "api-damaged", "product_id": product_id, "issue_type": "DAMAGED", "qty": 1, "notes": "Broken seal"})
        assert issue.status_code == 200
        issue_id = issue.json()["issue"]["id"]
        assert client.post(f"/ops/shipments/{shipment_id}/issues/{issue_id}/resolve", headers=headers, json={"resolution": "Discarded"}).status_code == 403
        incomplete = client.post(f"/ops/shipments/{shipment_id}/complete-receive", headers=headers)
        assert incomplete.status_code == 409 and incomplete.json()["detail"]["code"] == "PARTIAL_RECEIPT_REQUIRES_MANAGER"
        assert client.post(f"/ops/shipments/{shipment_id}/leave", headers=headers).status_code == 200
        assert client.post(f"/ops/shipments/{shipment_id}/open", headers=headers, json={}).status_code == 200
        assert client.get("/ops/shipments/lookup", params={"code": "4ZOXV48Q"}).status_code == 401
        manager_login = client.post("/auth/login", json={"username": "supervisor", "password": "demo1234",
            "device_id": "PDA-MANAGER", "app_version": "0.5.2"})
        assert manager_login.status_code == 200
        manager_headers = {"Authorization": f"Bearer {manager_login.json()['access_token']}"}
        created = client.post("/ops/shipments", headers=manager_headers, json={
            "supplier_name": "Vendor", "lines": [{"product_id": "DEMO-AMBIENT-001", "expected_qty": 2}]})
        assert created.status_code == 200 and created.json()["label"].startswith("IN-")
        resolved = client.post(f"/ops/shipments/{shipment_id}/issues/{issue_id}/resolve", headers=manager_headers,
            json={"resolution": "Rejected units quarantined"})
        assert resolved.status_code == 200 and resolved.json()["open_issues"] == 0
        partial = client.post(f"/ops/shipments/{shipment_id}/manager-close-receive", headers=manager_headers)
        assert partial.status_code == 200 and partial.json()["missing_units"] == 2
    finally:
        app.dependency_overrides.clear()
