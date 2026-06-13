# Protocol Case Law

This file is non-normative. The hard rules live in `collection_protocol.md`.

Use this file for examples, cleanup precedent, and recurring failure modes.

## Count Only Primary Payload

- Calendar helpers such as `obs_year_u16`, `obs_month_u8`, `obs_day_u8`, and `obs_hour_u8` are auxiliary.
- Alignment metadata, masks, bookkeeping arrays, and similar helper series may be stored when justified.
- They must not help a recipe pass acceptance floors.

## Thin Scope Failures

Reject recipes whose documented identity is intrinsically tiny even after exhausting the same scope:

- one fixed entity
- one repo snapshot
- one package page
- one arbitrary search query
- one ranked-feed slice
- one year when the full historical corpus is still tiny

If "saving" the recipe would require changing from one entity to many entities, from one query to general crawling, or from one narrow slice to a different corpus definition, that is a different recipe, not an expansion.

## Aggregate-Only Salvage

Reject recipes that clear the aggregate floor mainly by multiplying trivial samples.

Some small samples are fine. A dataset is not fine when most samples are tiny and the only acceptance story is "there are many of them."

## Homogeneity

Reject bundles that combine unrelated indicators merely because they share:

- the same portal
- the same API
- the same cadence
- the same country
- the same publisher

Accept only bundles whose material type, generation process, cadence, and unit semantics still read as one coherent dataset.

## Claimed Scope Must Be Real

If a recipe claims `50` sites, `500` entities, or some other target scope, the accepted output must actually realize that scope or be narrowed before acceptance.

Do not leave aspirational scope text in the manifest or README.

## Derived Numeric Representations

Accept only when the representation is:

- deterministic
- pinned
- machine-facing
- operationally real

Reject:

- arbitrary local remaps
- width mirrors
- helper overlays
- synthetic feature engineering
- duplicated views of the same underlying fact solely to inflate volume
