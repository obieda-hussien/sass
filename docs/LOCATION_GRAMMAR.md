# Location grammar

## Goals

A location identifier should encode enough physical context for a human to navigate while the location-master record carries operational metadata that should not be guessed from text alone.

## Canonical physical form

```text
P-{floor}-{classification?}-{fixture}{aisle}{level}{slot}
```

Examples:

```text
P-1-A115E181
P-1-H119C160
P-1-R120D211
P-1-X115N112
P-1-C124A110
P-1-F129F142
P-1-HAZ-A123E110
P-1-HAZ-X119T110
P-1-HRV132A110
```

### Dimensions

`P-1`
: Physical floor/site-space prefix.

`classification`
: Optional handling or security overlay such as `HAZ` or `HRV`.

`fixture`
: Physical storage form.

`aisle`
: Three-digit rack/aisle family.

`level`
: Vertical level letter. Level labels can also have a site-configured color for fast visual acquisition.

`slot`
: Three-digit bin/position number.

## Fixture semantics currently modeled

| Fixture | Meaning |
|---|---|
| A | general ambient shelf |
| V | produce / vegetables |
| D | bulk/liquid-oriented shelf |
| X | drawer storage |
| H | hanging peg storage |
| T | special metal/display shelf |
| R | wire basket / bagged snacks and chips |
| C | chilled storage |
| F | frozen storage |

The physical fixture and the handling classification are intentionally separate. For example, a hazardous product can be stored in an `A` shelf or an `X` drawer.

## Logical workflow locations

```text
TSCRET001      temporary ambient unpack/returns
TSCRETCHL01    temporary chilled unpack/returns
TSCRETFRZ01    temporary frozen unpack/returns
DMG            damaged / quarantined stock
SPECIAL        exception location; exact site meaning is configurable
PICKTOTE:{id}  virtual server-side location representing physically picked goods
```

Logical locations are real accounting locations even when they are not customer-pickable shelves.

## Visual-level color

The seed configuration knows only the confirmed initial mappings:

```text
A -> GREEN
B -> BLUE
C -> YELLOW
```

The rest must be loaded from site configuration rather than guessed.
