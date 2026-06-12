# Below-Floor Triage

This report turns the remaining accepted `below_floor` set into cleanup actions.

Current accepted audit baseline after `f866f7e`:

- `ok`: `127`
- `below_floor`: `246`
- `broken`: `0`

The remaining below-floor set falls into three different buckets:

1. `remove_now`
   - standalone recipes that are intrinsically too thin, snapshot-like, or too weak to justify keeping while a broader replacement is designed
2. `merge_or_replace_family`
   - over-fragmented source families where the source is fine, but the one-recipe-per-indicator/series split is wrong
   - replacements must remain homogeneous by material, cadence, and unit semantics; same API alone is not enough
3. `rewrite_expand_scope`
   - narrow recipes that should survive only if they are widened materially

## Remove Next

These are the clearest next removal candidates. The issue is not just that they are under floor; it is that the current standalone recipe shape is too thin to defend.

| dataset_id | total_values | total_sample_bytes | why |
|---|---:|---:|---|
| `open_notify_iss` | 3 | 12 | single live snapshot; too thin even if technically numeric |
| `pypistats_recent` | 3 | 24 | one-package recent counter snapshot; replace with a broader package/time recipe or drop |
| `census_geocoder` | 6 | 32 | single-query geocoder output; not a meaningful standalone dataset |
| `nominatim_berlin` | 6 | 34 | single-query geocoder output; same issue |
| `frankfurter_usd_rates` | 30 | 240 | one-day FX rates snapshot; replace with a real time-range recipe or drop |
| `lobsters_hottest` | 100 | 350 | one ranked page snapshot; too thin and ephemeral |
| `rickandmorty_characters` | 100 | 240 | thin fictional API slice with weak numeric density |

These should be removed before spending more effort expanding harder cases.

## Merge Or Replace Whole Families

These are not “bad sources.” They are bad recipe shapes. The current one-recipe-per-indicator split produces dozens of tiny accepted recipes. Some should become a smaller number of homogeneous family recipes. Others should be removed if no homogeneous consolidation makes sense.

### FRED single-series recipes (`24`)

- `fred_real_gdp_quarterly`
- `fred_capacity_utilization_monthly`
- `fred_civilian_labor_force_monthly`
- `fred_consumer_sentiment_monthly`
- `fred_core_cpi_monthly`
- `fred_cpi_all_items_monthly`
- `fred_federal_funds_monthly`
- `fred_housing_starts_monthly`
- `fred_industrial_production_monthly`
- `fred_labor_force_participation_monthly`
- `fred_m2_money_stock_monthly`
- `fred_payroll_employment_monthly`
- `fred_pce_price_index_monthly`
- `fred_ppi_all_commodities_monthly`
- `fred_unemployment_level_monthly`
- `fred_unemployment_rate_monthly`
- `fred_fed_balance_sheet_weekly`
- `fred_mortgage_30y_weekly`
- `fred_initial_claims_weekly`
- `fred_sp500_daily`
- `fred_treasury_10y_daily`
- `fred_treasury_2y_daily`
- `fred_treasury_30y_daily`
- `fred_wti_crude_daily`

Action:
- replace with a few homogeneous FRED bundles rather than keep 24 thin standalones
- examples that may be coherent: labor monthly, rates daily, macro monthly
- do not collapse all FRED indicators into one mixed bundle

### ECB FX single-pair recipes (`19`)

All `ecb_fx_*_eur_daily` recipes are below floor individually.

Action:
- replace with a homogeneous ECB FX matrix recipe instead of keeping one currency-pair recipe per dataset

### World Bank single-indicator recipes (`16`)

All current `world_bank_*` indicator standalones are too small individually.

Action:
- replace with a few homogeneous World Bank bundles where possible
- if indicators cannot be grouped coherently by material, remove the thin standalones instead of building one mixed bundle

### IMF single-indicator recipes (`7`)

All current `imf_*` indicator standalones are too small individually.

Action:
- replace with a few homogeneous IMF bundles where possible
- avoid one mixed IMF grab-bag

### OWID single-indicator recipes (`20`)

All current `owid_*` indicator standalones are too small individually.

Action:
- replace with a few homogeneous OWID bundles where possible
- remove thin standalones that do not fit a coherent bundle

### Eurostat single-indicator recipes (`7`)

Current monthly per-indicator Eurostat recipes are individually too small.

Action:
- replace with a few homogeneous Eurostat bundles where possible
- avoid mixing unrelated monthly materials just because they come from Eurostat

### SEC companyfacts single-metric recipes (`5`)

- `sec_companyfacts_assets_quarterly`
- `sec_companyfacts_cash_and_equivalents_quarterly`
- `sec_companyfacts_net_income_quarterly`
- `sec_companyfacts_operating_income_quarterly`
- `sec_companyfacts_stockholders_equity_quarterly`

Action:
- replace with a coherent multi-metric companyfacts recipe only if the selected metrics remain part of one interpretable financial-statement material group
- otherwise split into a small number of homogeneous bundles or remove the weakest standalones

## Rewrite / Expand Scope

These are under floor because the current recipe is too narrow, not because the source family is inherently too small.

Representative examples:

- `pubchem_compound_properties`
- `github_linux_repo_snapshot`
- `pypi_requests_json`
- `nobel_prizes`
- `rubygems_search`
- `metmuseum_objects`
- `bls_cpi_series`
- `jolpica_f1_results`
- `biorxiv_details`
- `dryad_search`
- `wikidata_sparql`
- `maven_central_search`
- `internet_archive_metadata`
- `packagist_packages`
- `gutendex_books`
- `nasa_neows_feed`
- `library_of_congress_items`
- `anilist_media`
- `semanticscholar_papers`
- `dockerhub_repositories`
- `openlibrary_subjects`
- `orcid_search`
- `europe_pmc_search`
- `openlibrary_search`
- `wger_exercises`
- `arxiv_cs_recent`
- `osf_preprints`
- `stackexchange_top_questions_jan_2024`
- `hn_algolia_search`
- `cratesio_crates`
- `hex_packages`
- `osm_overpass_cafes`
- `musicbrainz_recordings`
- `openfoodfacts_products`
- `openfda_*`
- `openalex_*`
- `npm_search_packages_large`
- `nuget_search`
- `gitlab_projects`
- `doaj_articles`
- `huggingface_datasets`
- `launchlibrary_upcoming`
- `itunes_search`
- `scryfall_cards`
- `openml_tasks_large`
- `nih_reporter_projects`
- `figshare_articles`
- `gbif_datasets`
- `geoboundaries_all_adm0`
- `eia_series_petroleum`
- `gwas_catalog_studies`
- `pride_projects_search`

Action:
- widen pagination
- widen time windows
- widen entity coverage
- stop using one-page or one-query slices as accepted endpoints

## Recommended Order

1. remove the `remove_now` set
2. stop carrying fragmented family standalones by planning homogeneous family-level replacements
3. only then spend rewrite effort on the narrow but salvageable recipes

That order removes the most obvious noise first and avoids spending effort polishing recipes that should really be merged away.
