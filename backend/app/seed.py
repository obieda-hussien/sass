from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from .location_parser import level_color, parse_location
from .models import Barcode, Device, InventoryBalance, Location, Product, User
from .security import hash_password


def ensure_location(db: Session, location_id: str) -> Location:
    existing = db.get(Location, location_id)
    if existing:
        return existing
    p = parse_location(location_id)
    loc = Location(
        id=p.canonical,
        floor=p.floor,
        classification=p.classification,
        fixture_type=p.fixture_type,
        aisle=p.aisle,
        level=p.level,
        slot=p.slot,
        temperature_class=p.temperature_class,
        handling_class=p.handling_class,
        logical=p.logical,
        pickable=p.pickable,
        stowable=p.stowable,
        sellable=p.sellable,
        color_code=level_color(p.level) if p.level else None,
    )
    db.add(loc)
    db.flush()
    return loc


def seed_demo(db: Session) -> None:
    if db.scalar(select(User).where(User.username == "picker1")) is None:
        db.add(User(username="picker1", password_hash=hash_password("demo1234"), role="PICKER"))
        db.add(User(username="supervisor", password_hash=hash_password("demo1234"), role="SUPERVISOR"))
    if db.get(Device, "PDA-DEMO-001") is None:
        db.add(Device(id="PDA-DEMO-001", trusted=True, app_version="0.1.0"))

    for loc in [
        "P-1-A101A110", "P-1-A115E181", "P-1-V112A110", "P-1-D121B120",
        "P-1-X115N112", "P-1-H119C160", "P-1-T113D120", "P-1-R120D211",
        "P-1-C124A110", "P-1-F129F142", "P-1-HAZ-A123E110", "P-1-HAZ-X119T110",
        "P-1-HRV132A110", "TSCRET001", "TSCRETCHL01", "TSCRETFRZ01", "DMG", "SPECIAL",
    ]:
        ensure_location(db, loc)

    products = [
        ("DEMO-AMBIENT-001", "Demo pasta", "AMBIENT", "STANDARD", "6220000000001", "P-1-A101A110", 40),
        ("DEMO-PRODUCE-001", "Demo vegetables", "AMBIENT", "STANDARD", "6220000000002", "P-1-V112A110", 24),
        ("DEMO-CHIPS-001", "Demo chips", "AMBIENT", "STANDARD", "6220000000003", "P-1-R120D211", 60),
        ("DEMO-CHILLED-001", "Demo chilled milk", "CHILLED", "STANDARD", "6220000000004", "P-1-C124A110", 30),
        ("DEMO-FROZEN-001", "Demo frozen item", "FROZEN", "STANDARD", "6220000000005", "P-1-F129F142", 20),
        ("DEMO-HAZ-001", "Demo aerosol", "AMBIENT", "HAZ", "6220000000006", "P-1-HAZ-A123E110", 15),
        ("DEMO-HRV-001", "Demo high-value accessory", "AMBIENT", "HRV", "6220000000007", "P-1-HRV132A110", 8),
    ]
    for asin, title, temp, handling, barcode, loc_id, qty in products:
        product = db.scalar(select(Product).where(Product.asin == asin))
        if product is None:
            product = Product(asin=asin, title=title, temperature_class=temp, handling_class=handling)
            db.add(product)
            db.flush()
            db.add(Barcode(code=barcode, product_id=product.id))
            db.add(InventoryBalance(location_id=loc_id, product_id=product.id, qty_on_hand=qty, qty_reserved=0))
    db.flush()
