# Cleanup Candidates

Current acceptance floor: `10,000` primary values or `100 KB` primary sample bytes, plus `1,000` minimum median primary sample values.

- source of truth: `reports/accepted_recipe_audit.tsv`
- `ok`: `122`
- `below_floor`: `199`
- `broken`: `0`

This file is the short operational queue. Detailed policy for family cleanup lives in
`reports/below_floor_triage.md` and `reports/family_homogeneity_policy.md`.

Some small samples are acceptable. What is no longer acceptable is a recipe whose
typical primary sample is tiny and which reaches usefulness only by stacking many such samples.

## Hygiene Completed In This Pass

- remove empty residual directories left behind by previously removed recipes
- regenerate quality reports against currently accepted manifests only
- drop stale references to already removed snapshot recipes from this queue

## Step 2 Completed In This Pass

- remove `pubchem_compound_properties`
- remove `github_linux_repo_snapshot`
- remove `pypi_requests_json`
- remove `nobel_prizes`
- remove `ror_organizations`
- remove `metmuseum_objects`
- remove `bls_cpi_series`
- remove `jolpica_f1_results`
- remove `pokeapi_pokemon`
- remove `hackernews_topstories`
- remove `nagerdate_holidays`
- remove `noaa_swpc_planetary_k_index`

## Median-Sample Removals

- remove `ecb_fx_eur_daily_matrix`
- remove `tourism_monthly_aus`

## Remove First: Tiny Non-Family Standalones

These remain accepted but are so small that they are the easiest next removal batch.
The common failure mode is a one-query, one-page, one-entity, or otherwise intrinsically
thin recipe shape rather than a source-family problem.

- `biorxiv_details` — values=150, bytes=390, sample_rows=5
- `dryad_search` — values=160, bytes=600, sample_rows=8
- `internet_archive_metadata` — values=200, bytes=1200, sample_rows=2
- `openbrewerydb_breweries` — values=246, bytes=1640, sample_rows=3
- `gutendex_books` — values=256, bytes=576, sample_rows=8
- `nasa_neows_feed` — values=270, bytes=1305, sample_rows=6
- `library_of_congress_items` — values=276, bytes=1016, sample_rows=5
- `anilist_media` — values=295, bytes=837, sample_rows=6
- `weathergov_stations` — values=300, bytes=2000, sample_rows=3
- `esco_occupations` — values=355, bytes=639, sample_rows=5
- `orcid_search` — values=390, bytes=780, sample_rows=4
- `europe_pmc_search` — values=400, bytes=800, sample_rows=4
- `wger_exercises` — values=400, bytes=800, sample_rows=4
- `arxiv_cs_recent` — values=400, bytes=1200, sample_rows=4
- `osf_preprints` — values=400, bytes=1300, sample_rows=4
- `stackexchange_top_questions_jan_2024` — values=400, bytes=1400, sample_rows=4
- `cratesio_crates` — values=400, bytes=2000, sample_rows=4
- `hex_packages` — values=400, bytes=2600, sample_rows=4
- `osm_overpass_cafes` — values=400, bytes=2600, sample_rows=4
- `musicbrainz_recordings` — values=476, bytes=1046, sample_rows=5
- `musicbrainz_release_groups` — values=491, bytes=982, sample_rows=5
- `openfoodfacts_products` — values=491, bytes=1870, sample_rows=5
- `inaturalist_observations` — values=495, bytes=1188, sample_rows=5
- `openfda_drug_event` — values=495, bytes=1683, sample_rows=5
- `pokemontcg_cards` — values=498, bytes=1071, sample_rows=6
- `gbif_occurrence` — values=498, bytes=2284, sample_rows=5
- `treasury_avg_interest_rates` — values=500, bytes=1000, sample_rows=5
- `crossref_funders` — values=500, bytes=1200, sample_rows=5
- `medrxiv_details` — values=500, bytes=1300, sample_rows=5
- `artic_artworks_search` — values=500, bytes=1400, sample_rows=5
- `figshare_articles` — values=500, bytes=1400, sample_rows=5
- `nvd_cves_recent` — values=500, bytes=1400, sample_rows=5
- `nuget_search` — values=500, bytes=1500, sample_rows=5

Count guide:
- tiny non-family standalones with `<= 500` values: `34`
- non-family below-floor recipes with `501-3999` values: `62`
- non-family below-floor recipes with `>= 4000` values: `20`

## Family Cleanup Queue

These are not obvious removals. They are fragmented source families that need either
homogeneous consolidation or selective pruning.

- `fred_*`: `24`
- `world_bank_*`: `16`
- `owid_*`: `20`
- `imf_*`: `7`
- `eurostat_*`: `7`
- `sec_companyfacts_*`: `5`

## Later: Rewrite / Expand

These are below floor but may survive if materially widened without violating protocol.
Representative examples:

- `openml_tasks_large`
- `dataone_solr`
- `dataone_solr_large_retry`
- `usgs_daily_values_large`
- `nasa_donki_cme`
- `nasa_donki_flr`
- `coinpaprika_tickers`
- `cisa_kev_catalog`
- `jpl_cad_2024`

## Recently Fixed Degenerate Series

- `covertype_uci`: dropped ultra-sparse one-hot columns `21`, `22`, `29`, `39`, `50`, `51`
- `cran_packages`: dropped constant `cran_archived_flag`
- `geonames_postal_fixed`: dropped broken `geonames_postal_admin1_code_u8`
- `gharchive_hourly_events_20240101_00`: dropped constant `gharchive_public`
- `hgnc_complete_set_json`: dropped constant `hgnc_status_length_u8`
- `universities_domains_list`: dropped constant `universities_alpha_two_code_length`
- `usgs_quakes_month`: dropped constant `usgs_quake_tsunami`
- `who_atlas_gisah`: dropped constant `who_gisah_spatial_dim_length_u8` and `who_gisah_data_source_length_u8`
- `who_gho_observations`: dropped constant `who_gho_dim2_length_u8`
