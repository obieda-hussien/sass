from __future__ import annotations

from ..models import Location, Product


def storage_compatible(product: Product, location: Location) -> tuple[bool, str | None]:
    if not location.active or not location.stowable:
        return False, "DESTINATION_NOT_STOWABLE"
    if location.handling_class in {"DAMAGE", "RETURNS", "SPECIAL"}:
        return True, None
    if product.temperature_class != location.temperature_class:
        return False, "TEMPERATURE_MISMATCH"
    if product.handling_class == "HAZ" and location.handling_class != "HAZ":
        return False, "HAZ_LOCATION_REQUIRED"
    if product.handling_class == "HRV" and location.handling_class != "HRV":
        return False, "HRV_LOCATION_REQUIRED"
    if product.handling_class == "STANDARD" and location.handling_class in {"HAZ", "HRV"}:
        return False, "CLASSIFICATION_MISMATCH"
    return True, None
