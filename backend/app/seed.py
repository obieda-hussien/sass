from __future__ import annotations

from sqlalchemy import select

from .database import SessionLocal, create_schema
from .models import Product
from .services import adjust_inventory, create_product, ensure_location


LOCATIONS = [
    ("P-1-A101A110", None),
    ("P-1-A101B110", None),
    ("P-1-V112A110", "PRODUCE"),
    ("P-1-R120D211", None),
    ("P-1-H119C160", None),
    ("P-1-C124A110", None),
    ("P-1-F128A110", None),
    ("P-1-HAZA123E110", "HAZ"),
    ("P-1-HAZX119A110", "HAZ"),
    ("TSCRET001", None),
    ("TSCRETCHL01", None),
    ("TSCRETFRZ01", None),
    ("DMG", "DAMAGE"),
    ("SPECIAL", "SPECIAL"),
]


PRODUCTS = [
    ("MILK-1L", "Full Cream Milk 1L", "6222048703222", "CHILLED", "STANDARD"),
    ("CHIPS-001", "Potato Chips", "6220000000001", "AMBIENT", "STANDARD"),
    ("CABLE-USB-C", "USB-C Charging Cable", "6220000000002", "AMBIENT", "STANDARD"),
    ("SPRAY-001", "Aerosol Spray", "6220000000003", "AMBIENT", "HAZ"),
]


def seed() -> None:
    create_schema()
    db = SessionLocal()
    try:
        with db.begin():
            for code, handling in LOCATIONS:
                ensure_location(
                    db,
                    code,
                    handling_class_override=handling,
                    pickable=not code.startswith("TSCRET") and code not in {"DMG", "SPECIAL"},
                )

            for sku, title, barcode, temperature, handling in PRODUCTS:
                if not db.scalar(select(Product).where(Product.sku == sku)):
                    create_product(
                        db,
                        sku=sku,
                        title=title,
                        barcode=barcode,
                        temperature_class=temperature,
                        handling_class=handling,
                    )

            adjust_inventory(
                db,
                event_id="seed-milk",
                product_sku="MILK-1L",
                location_code="P-1-C124A110",
                delta=20,
                reason="SEED",
                actor_id="system",
                device_id=None,
            )
            adjust_inventory(
                db,
                event_id="seed-chips",
                product_sku="CHIPS-001",
                location_code="P-1-R120D211",
                delta=60,
                reason="SEED",
                actor_id="system",
                device_id=None,
            )
            adjust_inventory(
                db,
                event_id="seed-cable",
                product_sku="CABLE-USB-C",
                location_code="P-1-A101A110",
                delta=25,
                reason="SEED",
                actor_id="system",
                device_id=None,
            )
            adjust_inventory(
                db,
                event_id="seed-haz",
                product_sku="SPRAY-001",
                location_code="P-1-HAZA123E110",
                delta=12,
                reason="SEED",
                actor_id="system",
                device_id=None,
            )
    finally:
        db.close()


if __name__ == "__main__":
    seed()
