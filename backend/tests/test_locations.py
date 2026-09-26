from app.location_parser import parse_location


def test_location_grammar():
    ambient = parse_location("P-1-A115E181")
    assert ambient.fixture == "A"
    assert ambient.aisle == 115
    assert ambient.level == "E"
    assert ambient.slot == 181
    assert ambient.temperature.value == "AMBIENT"

    frozen = parse_location("P-1-F128A110")
    assert frozen.temperature.value == "FROZEN"

    haz = parse_location("P-1-HAZX119A110")
    assert haz.handling.value == "HAZ"
    assert haz.fixture == "X"

    unpack = parse_location("TSCRETCHL01")
    assert unpack.kind.value == "UNPACK"
    assert unpack.temperature.value == "CHILLED"
