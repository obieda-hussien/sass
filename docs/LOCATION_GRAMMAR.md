# Location grammar

Location codes are parsed into structured metadata rather than treated as opaque strings.

## Physical storage

Typical form:

```text
P-<floor>-<class?><fixture><aisle><level><slot>
```

Examples:

- `P-1-A115E181` — ambient shelf, aisle 115, level E, slot 181
- `P-1-V112A110` — produce
- `P-1-R120D211` — chips/bagged snack basket
- `P-1-H119C160` — hanging fixture
- `P-1-C124A110` — chilled
- `P-1-F128A110` — frozen
- `P-1-HAZA123E110` / `P-1-HAZ-A123E110` — hazardous + A fixture
- `P-1-HAZX119A110` / `P-1-HAZ-X119A110` — hazardous + X drawer

The storage classification and fixture are separate dimensions; HAZ can therefore be layered on A or X.

## Known fixture families

| Code | Meaning |
| --- | --- |
| A | ambient shelf |
| V | produce |
| D | bulk/liquids |
| X | drawers |
| H | hanging |
| T | special metal shelving |
| R | chips / bagged snacks |
| C | chilled |
| F | frozen |

## Operational locations

- `TSCRET001` — ambient unpack
- `TSCRETCHL01` — chilled unpack
- `TSCRETFRZ01` — frozen unpack
- `DMG` — damaged/quarantine
- `SPECIAL` — unresolved exception holding

## Visual level cue

The physical rack level letters progress bottom-to-top and may be color-coded so the picker can identify the vertical level before reading the full label. FulfillOS stores `level` as data so a client can render the same visual cue.
