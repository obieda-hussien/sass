from app.location_parser import parse_location, level_color


def test_standard_location():
    p = parse_location('P-1-A115E181')
    assert p.fixture_type == 'A'
    assert p.aisle == 115
    assert p.level == 'E'
    assert p.slot == 181
    assert p.temperature_class == 'AMBIENT'
    assert p.canonical == 'P-1-A115E181'


def test_haz_overlay_keeps_fixture():
    p = parse_location('P-1-HAZ-X119T110')
    assert p.classification == 'HAZ'
    assert p.fixture_type == 'X'
    assert p.handling_class == 'HAZ'
    assert p.canonical == 'P-1-HAZ-X119T110'


def test_temperature_specials():
    assert parse_location('TSCRET001').temperature_class == 'AMBIENT'
    assert parse_location('TSCRETCHL01').temperature_class == 'CHILLED'
    assert parse_location('TSCRETFRZ01').temperature_class == 'FROZEN'
    assert parse_location('DMG').sellable is False


def test_fixture_semantics():
    assert parse_location('P-1-V112A110').description.startswith('Produce')
    assert 'chips' in parse_location('P-1-R120D211').description.lower()
    assert parse_location('P-1-C124A110').temperature_class == 'CHILLED'
    assert parse_location('P-1-F129F142').temperature_class == 'FROZEN'


def test_level_colors_are_configurable_seed_values():
    assert level_color('A') == 'GREEN'
    assert level_color('B') == 'BLUE'
    assert level_color('C') == 'YELLOW'
