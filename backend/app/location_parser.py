from __future__ import annotations

import re
from dataclasses import dataclass

from .enums import HandlingClass, LocationKind, TemperatureClass


PHYSICAL = re.compile(
    r"^P-(?P<floor>\d+)-(?:(?P<hazard>HAZ)-)?"
    r"(?P<fixture>[AVDXHTRCF])(?P<aisle>\d{3})(?P<level>[A-Z])(?P<slot>\d{3})$"
)

SPECIALS: dict[str, tuple[LocationKind, TemperatureClass, HandlingClass]] = {
    "TSCRET001": (LocationKind.UNPACK, TemperatureClass.AMBIENT, HandlingClass.STANDARD),
    "TSCRETCHL01": (LocationKind.UNPACK, TemperatureClass.CHILLED, HandlingClass.STANDARD),
    "TSCRETFRZ01": (LocationKind.UNPACK, TemperatureClass.FROZEN, HandlingClass.STANDARD),
    "DMG": (LocationKind.DAMAGE, TemperatureClass.AMBIENT, HandlingClass.DAMAGE),
    "SPECIAL": (LocationKind.SPECIAL, TemperatureClass.AMBIENT, HandlingClass.SPECIAL),
}

FIXTURE_TEMPERATURE = {
    "C": TemperatureClass.CHILLED,
    "F": TemperatureClass.FROZEN,
}

FIXTURE_HANDLING = {
    "V": HandlingClass.PRODUCE,
}


@dataclass(frozen=True, slots=True)
class ParsedLocation:
    code: str
    kind: LocationKind
    floor: int | None
    fixture: str | None
    aisle: int | None
    level: str | None
    slot: int | None
    temperature: TemperatureClass
    handling: HandlingClass


def parse_location(code: str) -> ParsedLocation:
    normalized = code.strip().upper().replace(" ", "")

    if normalized in SPECIALS:
        kind, temperature, handling = SPECIALS[normalized]
        return ParsedLocation(
            code=normalized,
            kind=kind,
            floor=None,
            fixture=None,
            aisle=None,
            level=None,
            slot=None,
            temperature=temperature,
            handling=handling,
        )

    match = PHYSICAL.fullmatch(normalized)
    if not match:
        raise ValueError(f"Unsupported location code: {code!r}")

    fixture = match.group("fixture")
    handling = (
        HandlingClass.HAZ
        if match.group("hazard")
        else FIXTURE_HANDLING.get(fixture, HandlingClass.STANDARD)
    )
    temperature = FIXTURE_TEMPERATURE.get(fixture, TemperatureClass.AMBIENT)

    return ParsedLocation(
        code=normalized,
        kind=LocationKind.STORAGE,
        floor=int(match.group("floor")),
        fixture=fixture,
        aisle=int(match.group("aisle")),
        level=match.group("level"),
        slot=int(match.group("slot")),
        temperature=temperature,
        handling=handling,
    )


def is_compatible(
    *,
    product_temperature: TemperatureClass,
    product_handling: HandlingClass,
    location: ParsedLocation,
) -> bool:
    if location.kind in {LocationKind.DAMAGE, LocationKind.SPECIAL}:
        return True
    if product_temperature != location.temperature:
        return False
    if product_handling == HandlingClass.HAZ and location.handling != HandlingClass.HAZ:
        return False
    if product_handling == HandlingClass.HRV and location.handling not in {
        HandlingClass.HRV,
        HandlingClass.SPECIAL,
    }:
        # HRV storage can be explicitly tagged in DB even if code grammar is site-specific.
        return False
    return True
