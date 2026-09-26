from __future__ import annotations

from uuid import uuid4


def bootstrap(client):
    locations = ["P-1-R120D211", "DMG", "TSCRET001"]
    for code in locations:
        payload = {"code": code}
        if code == "DMG":
            payload["handling_class_override"] = "DAMAGE"
            payload["pickable"] = False
        response = client.post("/v1/locations", json=payload)
        assert response.status_code == 200, response.text

    assert client.post(
        "/v1/catalog/products",
        json={
            "sku": "CHIPS",
            "title": "Chips",
            "barcode": "6220000000001",
            "temperature_class": "AMBIENT",
            "handling_class": "STANDARD",
        },
    ).status_code == 200

    assert client.post(
        "/v1/inventory/adjust",
        json={
            "event_id": "stock-1",
            "product_sku": "CHIPS",
            "location_code": "P-1-R120D211",
            "delta": 10,
            "reason": "TEST",
        },
    ).status_code == 200

    task = client.post(
        "/v1/orders",
        json={
            "external_ref": str(uuid4()),
            "lines": [{"sku": "CHIPS", "quantity": 2}],
        },
    ).json()

    task = client.post(
        "/v1/tasks/offer", json={"associate_id": "picker-1"}
    ).json()
    task = client.post(
        f"/v1/tasks/{task['id']}/accept",
        json={"associate_id": "picker-1", "device_id": "pda-1"},
    ).json()
    return task


def test_duplicate_scan_is_idempotent(client):
    task = bootstrap(client)
    line = task["lines"][0]
    payload = {
        "event_id": "scan-001",
        "task_line_id": line["id"],
        "associate_id": "picker-1",
        "device_id": "pda-1",
        "client_sequence": 1,
        "client_task_version": task["version"],
        "location_code": line["locationCode"],
        "barcode": "6220000000001",
        "quantity": 1,
    }

    first = client.post(f"/v1/tasks/{task['id']}/scan", json=payload)
    assert first.status_code == 200, first.text
    second = client.post(f"/v1/tasks/{task['id']}/scan", json=payload)
    assert second.status_code == 200
    assert second.json()["status"] == "DUPLICATE"

    inventory = client.get("/v1/inventory/item/CHIPS").json()
    assert inventory["totalOnHand"] == 9


def test_stale_client_cannot_rewind_server_state(client):
    task = bootstrap(client)
    line = task["lines"][0]
    first = {
        "event_id": "scan-001",
        "task_line_id": line["id"],
        "associate_id": "picker-1",
        "device_id": "pda-1",
        "client_sequence": 1,
        "client_task_version": task["version"],
        "location_code": line["locationCode"],
        "barcode": "6220000000001",
        "quantity": 1,
    }
    committed = client.post(f"/v1/tasks/{task['id']}/scan", json=first).json()

    stale = dict(first)
    stale["event_id"] = "scan-002"
    stale["client_sequence"] = 2
    response = client.post(f"/v1/tasks/{task['id']}/scan", json=stale)
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "STALE_TASK_VERSION"

    resumed = client.post(
        "/v1/sync/reconcile",
        json={
            "device_id": "pda-1",
            "associate_id": "picker-1",
            "task_id": task["id"],
            "last_known_version": task["version"],
            "pending_event_ids": ["scan-001", "scan-002"],
        },
    ).json()
    assert resumed["serverVersion"] == committed["task"]["version"]
    assert resumed["committedEventIds"] == ["scan-001"]
    assert resumed["unknownEventIds"] == ["scan-002"]


def test_mid_pick_cancel_enters_recovery_and_releases_unpicked_reservation(client):
    task = bootstrap(client)
    line = task["lines"][0]
    scan = {
        "event_id": "scan-001",
        "task_line_id": line["id"],
        "associate_id": "picker-1",
        "device_id": "pda-1",
        "client_sequence": 1,
        "client_task_version": task["version"],
        "location_code": line["locationCode"],
        "barcode": "6220000000001",
        "quantity": 1,
    }
    client.post(f"/v1/tasks/{task['id']}/scan", json=scan)

    cancelled = client.post(
        f"/v1/tasks/{task['id']}/cancel",
        json={"reason": "CUSTOMER_CANCELLED", "actor_id": "order-service"},
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["state"] == "RECOVERY_REQUIRED"

    inventory = client.get("/v1/inventory/item/CHIPS").json()
    assert inventory["totalOnHand"] == 9
    assert inventory["totalReserved"] == 0
