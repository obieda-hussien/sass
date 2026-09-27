from __future__ import annotations

from dataclasses import dataclass
import re


@dataclass(frozen=True)
class ParsedLocation:
    raw: str
    canonical: str
    floor: str | None
    classification: str | None
    fixture_type: str | None
    aisle: int | None
    level: str | None
    slot: int | None
    temperature_class: str
    handling_class: str
    logical: bool
    pickable: bool
    stowable: bool
    sellable: bool
    description: str


FIXTURE_META = {
    "A": ("AMBIENT", "STANDARD", "Ambient shelf"),
    "V": ("AMBIENT", "STANDARD", "Produce / vegetables"),
    "D": ("AMBIENT", "STANDARD", "Bulk / liquids shelf"),
    "X": ("AMBIENT", "STANDARD", "Drawer storage"),
    "H": ("AMBIENT", "STANDARD", "Hanging peg storage"),
    "T": ("AMBIENT", "STANDARD", "Special metal/display shelf"),
    "R": ("AMBIENT", "STANDARD", "Wire basket / chips storage"),
    "C": ("CHILLED", "STANDARD", "Chilled storage"),
    "F": ("FROZEN", "STANDARD", "Frozen storage"),
}

SPECIAL = {
    "TSCRET001": ParsedLocation("TSCRET001", "TSCRET001", None, "RETURNS", None, None, None, None, "AMBIENT", "RETURNS", True, False, True, False, "Temporary ambient unpack/returns tote"),
    "TSCRETCHL01": ParsedLocation("TSCRETCHL01", "TSCRETCHL01", None, "RETURNS", None, None, None, None, "CHILLED", "RETURNS", True, False, True, False, "Temporary chilled unpack/returns tote"),
    "TSCRETFRZ01": ParsedLocation("TSCRETFRZ01", "TSCRETFRZ01", None, "RETURNS", None, None, None, None, "FROZEN", "RETURNS", True, False, True, False, "Temporary frozen unpack/returns tote"),
    "DMG": ParsedLocation("DMG", "DMG", None, "DAMAGE", None, None, None, None, "AMBIENT", "DAMAGE", True, False, True, False, "Damage/quarantine location"),
    "SPECIAL": ParsedLocation("SPECIAL", "SPECIAL", None, "SPECIAL", None, None, None, None, "AMBIENT", "SPECIAL", True, False, True, False, "Special exception bin"),
}

# Accepts forms like P-1-A115E181, P-1-HAZ-A123E110, HAZ-X119T112.
HRV_COMPACT = re.compile(r"^(?:P-(?P<floor>\d+)-)?HRV(?P<aisle>\d{3})(?P<level>[A-Z])(?P<slot>\d{3})$")

PHYSICAL = re.compile(
    r"^(?:(?P<prefix>P-(?P<floor>\d+)-))?"
    r"(?:(?P<classification>HAZ|HRV)-)?"
    r"(?P<fixture>[A-Z])(?P<aisle>\d{3})(?P<level>[A-Z])(?P<slot>\d{3})$"
)


def normalize(value: str) -> str:
    return value.strip().upper().replace(" ", "").replace("_", "-")


def parse_location(value: str) -> ParsedLocation:
    raw = value
    value = normalize(value)
    if value in SPECIAL:
        p = SPECIAL[value]
        return ParsedLocation(raw, p.canonical, p.floor, p.classification, p.fixture_type, p.aisle, p.level, p.slot,
                              p.temperature_class, p.handling_class, p.logical, p.pickable, p.stowable, p.sellable, p.description)

    hrv = HRV_COMPACT.match(value)
    if hrv:
        floor = hrv.group("floor") or "1"
        aisle = int(hrv.group("aisle"))
        level = hrv.group("level")
        slot = int(hrv.group("slot"))
        return ParsedLocation(
            raw=raw, canonical=f"P-{floor}-HRV{aisle:03d}{level}{slot:03d}", floor=floor,
            classification="HRV", fixture_type=None, aisle=aisle, level=level, slot=slot,
            temperature_class="AMBIENT", handling_class="HRV", logical=False, pickable=True,
            stowable=True, sellable=True, description="High-value storage",
        )

    m = PHYSICAL.match(value)
    if not m:
        raise ValueError(f"Unsupported location format: {raw}")

    floor = m.group("floor") or "1"
    classification = m.group("classification")
    fixture = m.group("fixture")
    aisle = int(m.group("aisle"))
    level = m.group("level")
    slot = int(m.group("slot"))

    temp, handling, description = FIXTURE_META.get(fixture, ("AMBIENT", "STANDARD", "General physical storage"))
    if classification == "HAZ":
        handling = "HAZ"
        description = f"Hazardous {description.lower()}"
    elif classification == "HRV":
        handling = "HRV"
        description = f"High-value {description.lower()}"

    canonical = f"P-{floor}-"
    if classification:
        canonical += f"{classification}-"
    canonical += f"{fixture}{aisle:03d}{level}{slot:03d}"

    return ParsedLocation(
        raw=raw,
        canonical=canonical,
        floor=floor,
        classification=classification,
        fixture_type=fixture,
        aisle=aisle,
        level=level,
        slot=slot,
        temperature_class=temp,
        handling_class=handling,
        logical=False,
        pickable=True,
        stowable=True,
        sellable=True,
        description=description,
    )


def level_color(level: str) -> str | None:
    # Site-configurable. These first three are based on the observed local visual scheme.
    return {"A": "GREEN", "B": "BLUE", "C": "YELLOW"}.get(level.upper())
