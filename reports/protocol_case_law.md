# Protocol Case Law

This file is non-normative. The hard rules live in `collection_protocol.md`.

Use this file for examples, cleanup precedent, and recurring failure modes.

## Count Only Primary Payload

- Calendar helpers such as `obs_year_u16`, `obs_month_u8`, `obs_day_u8`, and `obs_hour_u8` are not meaningful payload and should not be emitted as dataset series.
- Alignment metadata, masks, bookkeeping arrays, and similar helper material must not help a recipe pass acceptance floors.

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

## Single-Sample Families

A family should contain multiple homogeneous natural samples with the same field
meaning. A one-sample family is weak training material unless the source sample
is large enough to shard confidently. Treat roughly-100KB or sub-MB table-column
samples as insufficient even when they pass the historical audit floor.

If the only available shape is one full table column per field, the recipe must
either:

- produce multi-MB single-field samples that can be deterministically sharded, or
- be reshaped into multiple homogeneous natural samples without concatenating
  different field meanings.

The following Macrostrat recipes were removed on 2026-07-02 despite passing the
audit because they were one-sample-per-field table-column families and their
per-family samples were far below a shardable size:

- `macrostrat_columns`
- `macrostrat_sections`

`macrostrat_units` was left in place for separate review. Its per-field samples
are still single-sample families, but the source is materially larger than
columns/sections and may deserve a better repair path before deletion.

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

## Rejected Thin Catalog/Search Shapes

The following below-floor recipes were removed on 2026-07-02 because their
committed shape was not worth repairing. They should not be reintroduced as
one-page, ranked-list, arbitrary-search, single-entity, or weak metadata-table
recipes. The source may be reconsidered only as a materially different,
homogeneous, reproducible, and sufficiently large recipe.

Superseded by stronger replacements:

- `eia_petroleum_prices` -> `eia_series_petroleum`
- `eurostat_female_unemployment_monthly` -> `eurostat_unemployment_monthly`
- `eurostat_male_unemployment_monthly` -> `eurostat_unemployment_monthly`
- `gleif_lei_records_api` -> `gleif_lei_records`
- `openml_dataset_61` -> broader OpenML recipes
- `openml_datasets` -> broader OpenML recipes
- `worldbank_gdp_constant` -> use the `world_bank_*` family only if repaired as a coherent bundle
- `worldbank_population_total` -> use the `world_bank_*` family only if repaired as a coherent bundle

Discarded as weak one-page/search/ranked/catalog metadata shapes:

- `arxiv_ai_recent`
- `coingecko_top_markets`
- `deezer_chart`
- `disease_sh_countries`
- `doaj_articles`
- `geoboundaries_all_adm0`
- `gitlab_projects`
- `huggingface_datasets`
- `itunes_search`
- `launchlibrary_upcoming`
- `marine_regions_gazetteer`
- `npm_search_packages_large`
- `openbrewerydb_breweries`
- `openlibrary_editions`
- `rubygems_versions_large`
- `scryfall_cards`
- `tvmaze_shows`
- `wger_exercises`

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
