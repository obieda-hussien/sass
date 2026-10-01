import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.models import Barcode, InventoryBalance, Product, User
from app.models_ops import AdminAuditEvent, Shipment
from app.services.catalog import lookup_product, register_product
from app.services.ops_platform import OpsError, create_shipment


@pytest.fixture()
def catalog_client(db):
    from app.database import get_db
    from app.main import app
    app.dependency_overrides[get_db] = lambda: db
    try:
        client = TestClient(app)
        def headers(username, device):
            response = client.post("/auth/login", json={"username": username, "password": "demo1234", "device_id": device})
            assert response.status_code == 200
            return {"Authorization": f"Bearer {response.json()['access_token']}"}
        yield client, headers("supervisor", "PDA-MANAGER"), headers("picker1", "PDA-DEMO-001")
    finally:
        app.dependency_overrides.clear()


def test_unknown_barcode_can_be_registered_then_used_in_a_shipment(catalog_client, db):
    client, manager, picker = catalog_client
    code = "6221073000849"
    assert client.get("/ops/catalog/lookup", params={"identifier": code}, headers=picker).json()["found"] is False
    result = client.post("/ops/catalog/register", headers=manager, json={
        "barcode": code, "sku": "REAL-ITEM-001", "title": "اسم الصنف الحقيقي", "storage_domain": "AMBIENT"})
    assert result.status_code == 200
    product = result.json()
    assert product["barcodes"] == [code] and product["active"]
    found = client.get("/ops/catalog/lookup", params={"identifier": code}, headers=picker).json()
    assert found["product"]["id"] == product["id"]
    created = client.post("/ops/shipments", headers=manager, json={
        "lines": [{"product_id": code, "expected_qty": 3}]})
    assert created.status_code == 200
    assert created.json()["lines"][0]["title"] == "اسم الصنف الحقيقي"
    assert db.scalar(select(func.count()).select_from(InventoryBalance).where(InventoryBalance.product_id == product["id"])) == 0
    assert db.scalar(select(AdminAuditEvent).where(AdminAuditEvent.action == "REGISTER_PRODUCT", AdminAuditEvent.entity_id == product["id"]))


def test_catalog_writes_require_manager_permission(catalog_client):
    client, _, picker = catalog_client
    assert client.post("/ops/catalog/register", headers=picker, json={"barcode": "NEW", "sku": "SKU"}).status_code == 403
    assert client.post("/ops/catalog/products/unknown/activate", headers=picker).status_code == 403
    assert client.get("/ops/catalog/lookup", params={"identifier": "NEW"}).status_code == 401


def test_existing_sku_links_an_alias_idempotently_without_changing_metadata(db):
    with db.begin():
        manager = db.scalar(select(User).where(User.username == "supervisor"))
        original = db.scalar(select(Product).where(Product.asin == "DEMO-AMBIENT-001"))
        title = original.title
        args = dict(barcode="7451789038686", sku=original.asin, title="Do not overwrite", storage_domain="AMBIENT", manager_id=manager.id)
        assert register_product(db, **args).id == original.id
        assert register_product(db, **args).id == original.id
        assert original.title == title
        assert lookup_product(db, args["barcode"]).id == original.id
        assert db.scalar(select(func.count()).select_from(Barcode).where(Barcode.code == args["barcode"])) == 1


def test_barcode_cannot_be_reassigned_or_shadow_a_sku(db):
    with db.begin():
        manager = db.scalar(select(User).where(User.username == "supervisor"))
        original = db.scalar(select(Product).where(Product.asin == "DEMO-AMBIENT-001"))
        code = db.scalar(select(Barcode.code).where(Barcode.product_id == original.id))
        for barcode, sku in [(code, "UNRELATED"), (original.asin, "UNRELATED"), ("NEW", code)]:
            with pytest.raises(OpsError) as exc:
                register_product(db, barcode=barcode, sku=sku, title="Wrong item", storage_domain="AMBIENT", manager_id=manager.id)
            assert exc.value.code == "BARCODE_CONFLICT"


def test_existing_product_storage_rules_cannot_be_overwritten(db):
    with db.begin():
        manager = db.scalar(select(User).where(User.username == "supervisor"))
        with pytest.raises(OpsError) as exc:
            register_product(db, barcode="NEW", sku="DEMO-AMBIENT-001", title="Ignore", storage_domain="FROZEN", manager_id=manager.id)
        assert exc.value.code == "ZONE_MISMATCH"
        assert db.scalar(select(Barcode).where(Barcode.code == "NEW")) is None


def test_legacy_barcode_sku_collision_cannot_be_silently_accepted(db):
    with db.begin():
        manager = db.scalar(select(User).where(User.username == "supervisor"))
        original = db.scalar(select(Product).where(Product.asin == "DEMO-AMBIENT-001"))
        other = Product(asin="OTHER", title="Another item")
        db.add(other)
        db.flush()
        db.add(Barcode(code=original.asin, product_id=other.id))
        db.flush()
        with pytest.raises(OpsError) as exc:
            register_product(db, barcode=original.asin, sku=original.asin, title=None, storage_domain="AMBIENT", manager_id=manager.id)
        assert exc.value.code == "BARCODE_CONFLICT"


@pytest.mark.parametrize("domain,temp,handling", [("AMBIENT", "AMBIENT", "STANDARD"), ("PRODUCE", "AMBIENT", "STANDARD"),
    ("CHILLED", "CHILLED", "STANDARD"), ("FROZEN", "FROZEN", "STANDARD"), ("HAZ", "AMBIENT", "HAZ"), ("HRV", "AMBIENT", "HRV")])
def test_registration_preserves_storage_and_handling_classes(db, domain, temp, handling):
    with db.begin():
        manager = db.scalar(select(User).where(User.username == "supervisor"))
        product = register_product(db, barcode=f"NEW-{domain}", sku=f"SKU-{domain}", title="Real item", storage_domain=domain, manager_id=manager.id)
        assert (product.temperature_class, product.handling_class) == (temp, handling)


def test_inactive_product_requires_explicit_activation(catalog_client, db):
    client, manager, _ = catalog_client
    with db.begin():
        product = db.scalar(select(Product).where(Product.asin == "DEMO-AMBIENT-001"))
        product.active = False
        product_id = product.id
    assert client.get("/ops/catalog/lookup", headers=manager, params={"identifier": "DEMO-AMBIENT-001"}).json()["product"]["active"] is False
    result = client.post("/ops/catalog/register", headers=manager, json={"barcode": "ALIAS", "sku": "DEMO-AMBIENT-001"})
    assert result.status_code == 409 and result.json()["detail"]["code"] == "PRODUCT_INACTIVE"
    assert client.post(f"/ops/catalog/products/{product_id}/activate", headers=manager).json()["active"]
    assert client.post("/ops/catalog/register", headers=manager, json={"barcode": "ALIAS", "sku": "DEMO-AMBIENT-001"}).status_code == 200
    assert db.scalar(select(AdminAuditEvent).where(AdminAuditEvent.action == "ACTIVATE_PRODUCT", AdminAuditEvent.entity_id == product_id))


def test_missing_product_error_identifies_row_and_rolls_back_shipment(catalog_client, db):
    client, manager, _ = catalog_client
    result = client.post("/ops/shipments", headers=manager, json={"label": "BAD-PRODUCT", "lines": [
        {"product_id": "DEMO-AMBIENT-001", "expected_qty": 1}, {"product_id": "UNKNOWN", "expected_qty": 1}]})
    assert result.status_code == 409
    assert "Item 2: UNKNOWN" in result.json()["detail"]["message"]
    assert db.scalar(select(Shipment).where(Shipment.label == "BAD-PRODUCT")) is None


def test_new_product_requires_name_and_valid_storage(catalog_client):
    client, manager, _ = catalog_client
    for body, code in [({"barcode": "NEW", "sku": "NEW", "title": " "}, "PRODUCT_NAME_REQUIRED"),
                       ({"barcode": "NEW", "sku": "NEW", "title": "Real item", "storage_domain": "WRONG"}, "BAD_STORAGE_DOMAIN")]:
        result = client.post("/ops/catalog/register", headers=manager, json=body)
        assert result.status_code == 409 and result.json()["detail"]["code"] == code
