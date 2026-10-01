"""Explicit manager registration; catalog writes never create inventory."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Barcode, Product
from .governance import audit_event
from .ops_platform import OpsError, SHIPMENT_DOMAINS, _shipment_temp_handling


def lookup_product(db: Session, identifier: str) -> Product | None:
    identifier = identifier.strip()
    product = db.get(Product, identifier) or db.scalar(select(Product).where(Product.asin == identifier))
    if product is None:
        mapping = db.scalar(select(Barcode).where(Barcode.code == identifier))
        product = db.get(Product, mapping.product_id) if mapping else None
    return product


def product_payload(db: Session, product: Product) -> dict:
    return {
        "id": product.id, "sku": product.asin, "title": product.title,
        "active": product.active, "temperature_class": product.temperature_class,
        "handling_class": product.handling_class,
        "barcodes": list(db.scalars(select(Barcode.code).where(Barcode.product_id == product.id).order_by(Barcode.code))),
    }


def register_product(db: Session, *, barcode: str, sku: str, title: str | None,
                     storage_domain: str, manager_id: str) -> Product:
    barcode, sku = barcode.strip(), sku.strip()
    title = (title or "").strip()
    domain = storage_domain.strip().upper()
    if not barcode or not sku:
        raise OpsError("Enter the item barcode and SKU", "BAD_PRODUCT")
    if domain not in SHIPMENT_DOMAINS:
        raise OpsError("Unsupported storage domain", "BAD_STORAGE_DOMAIN")
    temp, handling = _shipment_temp_handling(domain)
    product = db.scalar(select(Product).where(Product.asin == sku).with_for_update())
    # UUIDs, SKU codes and barcodes must all identify the same product.
    sku_owner = lookup_product(db, sku)
    barcode_owner = lookup_product(db, barcode)
    if (sku_owner and (product is None or sku_owner.id != product.id)) or (barcode_owner and (product is None or barcode_owner.id != product.id)):
        raise OpsError("This barcode or SKU already identifies another product. Use its existing SKU; barcodes cannot be reassigned.", "BARCODE_CONFLICT")
    if product is None:
        if not title:
            raise OpsError("Enter the real product name before registering a new SKU", "PRODUCT_NAME_REQUIRED")
        product = Product(asin=sku, title=title, temperature_class=temp, handling_class=handling)
        db.add(product)
        db.flush()
        audit_event(db, actor_user_id=manager_id, action="REGISTER_PRODUCT", entity_type="PRODUCT",
                    entity_id=product.id, new_value={"sku": sku, "title": title, "storage_domain": domain})
    if not product.active:
        raise OpsError("This SKU is inactive. Check it and activate it before linking its barcode.", "PRODUCT_INACTIVE")
    if product.temperature_class != temp or product.handling_class != handling:
        raise OpsError(f"{product.title} belongs in {product.temperature_class}/{product.handling_class}; select that shipment zone", "ZONE_MISMATCH")
    mapping = db.scalar(select(Barcode).where(Barcode.code == barcode))
    if mapping is not None and mapping.product_id != product.id:
        raise OpsError("This barcode already belongs to another product and cannot be reassigned.", "BARCODE_CONFLICT")
    if mapping is None:
        db.add(Barcode(code=barcode, product_id=product.id))
        db.flush()
        audit_event(db, actor_user_id=manager_id, action="LINK_PRODUCT_BARCODE", entity_type="PRODUCT",
                    entity_id=product.id, new_value={"barcode": barcode})
    return product


def activate_product(db: Session, product: Product, manager_id: str) -> Product:
    if not product.active:
        product.active = True
        audit_event(db, actor_user_id=manager_id, action="ACTIVATE_PRODUCT", entity_type="PRODUCT",
                    entity_id=product.id, field_name="active", old_value=False, new_value=True)
    return product
