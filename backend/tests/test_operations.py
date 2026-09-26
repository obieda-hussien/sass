from sqlalchemy import select

from app.models import InventoryBalance, Product, User, Device
from app.services.operations import (
    OperationError, active_unpack, apply_cycle_count, boh_move, complete_unpack, damage_move,
    record_cycle_count, scan_unpack, start_cycle_count, start_unpack,
)


def actor(db):
    user = db.scalar(select(User).where(User.username == "picker1"))
    device = db.get(Device, "PDA-DEMO-001")
    db.commit()
    return user, device


def product(db, asin):
    p = db.scalar(select(Product).where(Product.asin == asin))
    db.commit()
    return p


def test_unpack_enforces_temperature_and_boh_compatibility(db):
    user, device = actor(db)
    chilled = product(db, "DEMO-CHILLED-001")
    session = start_unpack(db, "CHILLED", user.id, device.id)
    db.commit()
    session = db.get(type(session), session.id)
    result = scan_unpack(db, session, "unpack-1", chilled.id, 2)
    db.commit()
    assert result["tote_location_id"] == "TSCRETCHL01"

    summary = complete_unpack(db, session)
    db.commit()
    assert summary["status"] == "COMPLETED"
    assert "P-1-C124A110" in summary["items"][0]["compatible_destinations"]

    move = boh_move(
        db, event_id="boh-1", product_id=chilled.id, qty=2,
        source_location_id="TSCRETCHL01", destination_location_id="P-1-C124A110",
        user_id=user.id, device_id=device.id,
    )
    db.commit()
    assert move["destination_qty"] >= 2


def test_unpack_rejects_wrong_temperature(db):
    user, device = actor(db)
    frozen = product(db, "DEMO-FROZEN-001")
    session = start_unpack(db, "AMBIENT", user.id, device.id)
    db.commit()
    session = db.get(type(session), session.id)
    try:
        scan_unpack(db, session, "wrong-temp", frozen.id, 1)
        assert False, "expected temperature mismatch"
    except OperationError as e:
        db.rollback()
        assert e.code == "TEMPERATURE_MISMATCH"


def test_damage_moves_inventory_out_of_sellable_location(db):
    user, device = actor(db)
    ambient = product(db, "DEMO-AMBIENT-001")
    before = db.scalar(select(InventoryBalance).where(
        InventoryBalance.product_id == ambient.id,
        InventoryBalance.location_id == "P-1-A101A110",
    )).qty_on_hand
    db.commit()
    result = damage_move(
        db, event_id="dmg-1", product_id=ambient.id, qty=1,
        source_location_id="P-1-A101A110", reason="OPEN_PACKAGE",
        user_id=user.id, device_id=device.id,
    )
    db.commit()
    assert result["damage_qty"] == 1
    after = db.scalar(select(InventoryBalance).where(
        InventoryBalance.product_id == ambient.id,
        InventoryBalance.location_id == "P-1-A101A110",
    )).qty_on_hand
    assert after == before - 1


def test_cycle_count_adjustment_is_auditable_inventory_movement(db):
    user, device = actor(db)
    ambient = product(db, "DEMO-AMBIENT-001")
    session = start_cycle_count(db, "P-1-A101A110", user.id)
    db.commit()
    session = db.get(type(session), session.id)
    bal = db.scalar(select(InventoryBalance).where(
        InventoryBalance.product_id == ambient.id,
        InventoryBalance.location_id == "P-1-A101A110",
    ))
    counted = bal.qty_on_hand - 2
    db.commit()
    entry = record_cycle_count(db, session, ambient.id, counted)
    db.commit()
    assert entry.variance == -2
    session = db.get(type(session), session.id)
    result = apply_cycle_count(db, session, "COUNT_VERIFIED", user.id, device.id)
    db.commit()
    assert result["status"] == "COMPLETED"
    bal = db.scalar(select(InventoryBalance).where(
        InventoryBalance.product_id == ambient.id,
        InventoryBalance.location_id == "P-1-A101A110",
    ))
    assert bal.qty_on_hand == counted



def test_unpack_start_is_retry_safe_and_resumable(db):
    user, device = actor(db)
    first = start_unpack(db, "AMBIENT", user.id, device.id)
    db.commit()
    first_id = first.id

    second = start_unpack(db, "ambient", user.id, device.id)
    db.commit()
    assert second.id == first_id

    resumed = active_unpack(db, user.id, device.id, "AMBIENT")
    assert resumed is not None
    assert resumed.id == first_id
    assert resumed.tote_location_id == "TSCRET001"

    complete_unpack(db, resumed)
    db.commit()
    third = start_unpack(db, "AMBIENT", user.id, device.id)
    db.commit()
    assert third.id != first_id
