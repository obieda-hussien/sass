from sqlalchemy import select

from app.models import InventoryBalance, Product
from app.services.inventory import move_inventory


def test_inventory_move_is_idempotent(db):
    product = db.scalar(select(Product).where(Product.asin == "DEMO-AMBIENT-001"))
    src = db.scalar(select(InventoryBalance).where(
        InventoryBalance.product_id == product.id,
        InventoryBalance.location_id == "P-1-A101A110",
    ))
    before = src.qty_on_hand
    db.commit()

    first = move_inventory(
        db, event_id="evt-move-1", product_id=product.id, qty=2,
        source_location_id="P-1-A101A110", destination_location_id="TSCRET001", reason="TEST",
    )
    db.commit()
    second = move_inventory(
        db, event_id="evt-move-1", product_id=product.id, qty=2,
        source_location_id="P-1-A101A110", destination_location_id="TSCRET001", reason="TEST",
    )
    db.commit()

    src = db.scalar(select(InventoryBalance).where(
        InventoryBalance.product_id == product.id,
        InventoryBalance.location_id == "P-1-A101A110",
    ))
    assert first.duplicate is False
    assert second.duplicate is True
    assert src.qty_on_hand == before - 2
