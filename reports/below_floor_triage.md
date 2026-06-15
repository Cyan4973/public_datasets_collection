# Below-Floor Triage

This report turns the remaining accepted `below_floor` set into cleanup actions.

This is a policy-and-examples triage memo. The exact live inventory is
`reports/accepted_recipe_audit.tsv`.

Audit baseline when this triage memo was last refreshed:

- `ok`: `124`
- `below_floor`: `186`
- `broken`: `0`

The remaining below-floor set falls into three buckets:

1. `remove_now`: standalone recipes that are intrinsically too thin, snapshot-like, or too weak to justify keeping while a broader replacement is designed
2. `merge_or_replace_family`: over-fragmented source families where the source is fine, but the one-recipe-per-indicator/series split is wrong
3. `rewrite_expand_scope`: narrow recipes that should survive only if they are widened materially

## Remove Next

The current non-family standalones with `<= 500` primary values need
repair-or-remove triage before deletion. Many are one-query, one-page,
one-entity, or otherwise intrinsically narrow, but some source APIs can be
extended coherently. Per-recipe extension assessment lives in
`reports/tiny_standalone_extension_triage.md`.

Current count: `30`

| dataset_id | values | bytes | samples | median values | reasons |
|---|---:|---:|---:|---:|---|
| `gutendex_books` | 192 | 512 | 6 | 32 | `aggregate_floor,median_sample_floor` |
| `library_of_congress_items` | 232 | 928 | 4 | 44 | `aggregate_floor,median_sample_floor` |
| `openbrewerydb_breweries` | 246 | 1640 | 3 | 82 | `aggregate_floor,median_sample_floor` |
| `anilist_media` | 295 | 837 | 6 | 49 | `aggregate_floor,median_sample_floor` |
| `gbif_occurrence` | 298 | 1984 | 3 | 99 | `aggregate_floor,median_sample_floor` |
| `nuget_search` | 300 | 1200 | 3 | 100 | `aggregate_floor,median_sample_floor` |
| `osf_preprints` | 300 | 1200 | 3 | 100 | `aggregate_floor,median_sample_floor` |
| `weathergov_stations` | 300 | 2000 | 3 | 100 | `aggregate_floor,median_sample_floor` |
| `musicbrainz_recordings` | 382 | 952 | 4 | 94 | `aggregate_floor,median_sample_floor` |
| `arxiv_cs_recent` | 400 | 1200 | 4 | 100 | `aggregate_floor,median_sample_floor` |
| `cratesio_crates` | 400 | 2000 | 4 | 100 | `aggregate_floor,median_sample_floor` |
| `datacite_dois` | 400 | 1200 | 4 | 100 | `aggregate_floor,median_sample_floor` |
| `europe_pmc_search` | 400 | 800 | 4 | 100 | `aggregate_floor,median_sample_floor` |
| `gleif_lei_records` | 400 | 800 | 4 | 100 | `aggregate_floor,median_sample_floor` |
| `hex_packages` | 400 | 2600 | 4 | 100 | `aggregate_floor,median_sample_floor` |
| `ooni_measurements` | 400 | 1300 | 4 | 100 | `aggregate_floor,median_sample_floor` |
| `osm_overpass_cafes` | 400 | 2600 | 4 | 100 | `aggregate_floor,median_sample_floor` |
| `stackexchange_top_questions_jan_2024` | 400 | 1400 | 4 | 100 | `aggregate_floor,median_sample_floor` |
| `treasury_avg_interest_rates` | 400 | 800 | 4 | 100 | `aggregate_floor,median_sample_floor` |
| `wger_exercises` | 400 | 800 | 4 | 100 | `aggregate_floor,median_sample_floor` |
| `musicbrainz_release_groups` | 491 | 982 | 5 | 100 | `aggregate_floor,median_sample_floor` |
| `openfoodfacts_products` | 491 | 1870 | 5 | 98 | `aggregate_floor,median_sample_floor` |
| `inaturalist_observations` | 495 | 1188 | 5 | 99 | `aggregate_floor,median_sample_floor` |
| `pokemontcg_cards` | 498 | 1071 | 6 | 81 | `aggregate_floor,median_sample_floor` |
| `artic_artworks_search` | 500 | 1400 | 5 | 100 | `aggregate_floor,median_sample_floor` |
| `gitlab_projects` | 500 | 2000 | 5 | 100 | `aggregate_floor,median_sample_floor` |
| `huggingface_datasets` | 500 | 2000 | 5 | 100 | `aggregate_floor,median_sample_floor` |
| `medrxiv_details` | 500 | 1300 | 5 | 100 | `aggregate_floor,median_sample_floor` |
| `nvd_cves_recent` | 500 | 1400 | 5 | 100 | `aggregate_floor,median_sample_floor` |
| `pride_projects_search` | 500 | 1600 | 5 | 100 | `aggregate_floor,median_sample_floor` |

Use this table as the small-recipe queue, not as an automatic deletion list.

## Merge Or Replace Whole Families

These are not bad sources. They are bad recipe shapes. The current
one-recipe-per-indicator split produces dozens of tiny accepted recipes. Some
should become a smaller number of homogeneous family recipes. Others should be
removed if no homogeneous consolidation makes sense.

### FRED single-series recipes (`23`)

Action:
- replace with a few homogeneous FRED bundles rather than keep 23 thin standalones
- plausible groups: monthly labor, monthly macro, daily rates, weekly rates/claims
- do not collapse all FRED indicators into one mixed bundle

### World Bank single-indicator recipes (`16`)

Action:
- replace with a few homogeneous World Bank bundles where possible
- if indicators cannot be grouped coherently by material, remove the thin standalones instead of building one mixed bundle

### OWID single-indicator recipes (`20`)

Action:
- replace with a few homogeneous OWID bundles where possible
- remove thin standalones that do not fit a coherent bundle

### IMF single-indicator recipes (`7`)

Action:
- replace with a few homogeneous IMF bundles where possible
- avoid one mixed IMF grab-bag

### Eurostat single-indicator recipes (`7`)

Action:
- replace with a few homogeneous Eurostat bundles where possible
- avoid mixing unrelated monthly materials just because they come from Eurostat

### SEC companyfacts single-metric recipes (`5`)

Action:
- replace with a coherent multi-metric companyfacts recipe only if the selected metrics remain part of one interpretable financial-statement material group
- otherwise split into a small number of homogeneous bundles or remove the weakest standalones

## Rewrite / Expand Scope

These are under floor because the current recipe is too narrow, not because the
source is inherently too small. They may survive if materially widened without
violating protocol.

Current non-family below-floor backlog:
- `501-3999` values: `55`
- `>=4000` values: `24`

Representative high-value rewrite/expand candidates:
- `metacpan_releases_search_large`
- `cisa_kev_catalog`
- `coinpaprika_tickers`
- `nasa_donki_cme`
- `openml_tasks_large`
- `jpl_cad_2024`
- `nomis_employment`
- `openml_runs_large`
- `figshare_articles_large`
- `jhu_covid19_confirmed_global_daily`
- `jhu_covid19_confirmed_us_daily`
- `jhu_covid19_deaths_global_daily`
- `jhu_covid19_deaths_us_daily`
- `crossref_funders_large`
- `usgs_water_sites_rdb`
- `inspirehep_literature`
- `usgs_daily_values_large`
- `mitre_attack_enterprise`
- `dataone_solr`
- `dataone_solr_large_retry`
- `federalregister_documents_large`
- `europepmc_grants_large_retry`
- `taginfo_tags_popular`
- `taginfo_keys_all`

Action:
- widen pagination
- widen time windows
- widen entity coverage
- stop using one-page or one-query slices as accepted endpoints

## Recommended Order

1. decide the sparse-binary policy in `reports/degenerate_series_audit.tsv`
2. remove the `remove_now` standalone set
3. stop carrying fragmented family standalones by planning homogeneous family-level replacements
4. only then spend rewrite effort on the narrow but salvageable recipes

That order removes the most obvious noise first and avoids polishing recipes
that should really be merged away.
