# Scryfall Card Numerics (per year)

Numeric Magic: The Gathering card fields from the **Scryfall bulk data**, organized as
**one family per quantity** with **one sample per release year** — "many year-series of the
same quantity". Supersedes the earlier recipe, which captured only a single ~175-card
search page (hence below floor).

- Source: https://scryfall.com/docs/api/bulk-data (CC0 card data)
- Local raw payload: `${DATA_DIR:-.data}/downloads/scryfall_default_cards/cards.json`

## Families & samples

| family | quantity | type |
|---|---|---|
| `scryfall_cmc_u8` | converted mana cost / mana value | uint8 |
| `scryfall_edhrec_rank_u32` | EDHREC popularity rank | uint32 |
| `scryfall_price_usd_cents_u32` | market price (USD cents) | uint32 |

- **A sample** = one release year's values of a single quantity (e.g. all 2020 cards' mana
  values). Years come from `released_at`.
- **Samples/family** = number of years with `>= SCRYFALL_MIN_YEAR_RECORDS` non-constant
  values (default 1000); recent ~15 years of Magic clear this comfortably.

## Why the bulk file

The card search API returns ~175 cards per page; the bulk-data file is the full unique-card
set (~30k oracle cards, ~178 MB) in one download. The download URI is timestamped, so the
recipe resolves the current URI from the bulk-data listing at run time.

## Run

```sh
bash datasets/scryfall_default_cards/download.sh   # resolves URI, ~178 MB, resumable
bash datasets/scryfall_default_cards/build.sh
bash datasets/scryfall_default_cards/verify.sh
```

Tuning env vars: `SCRYFALL_BULK_TYPE` (default `oracle_cards`; `default_cards` for all
printings), `SCRYFALL_MIN_YEAR_RECORDS` (default 1000). Logs under
`${DATA_DIR:-.data}/logs/scryfall_default_cards/`.
