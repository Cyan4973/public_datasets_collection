# Constant Series Cleanup

Date: 2026-06-15

Scope: constant-valued findings only. This report intentionally excludes
`binary_sparse` rows from `reports/degenerate_series_audit.tsv`.

The current degenerate audit is sample-row based. A flagged row can mean either:

- a full manifest series is constant and should be removed from the recipe, or
- only some natural samples inside an otherwise useful series are constant and
  should be filtered without removing the whole series.

## Summary

- completed globally constant manifest-series removals: `94` series across `52` datasets
- remaining globally constant manifest series: `0`
- remaining partial constant-sample cases: `10` dataset/series pairs across `6` datasets
- sparse-binary cases: out of scope for this pass

Acceptance impact after rebuilding affected local indexes:

- `metacpan_releases_search_large` moved from `ok` to `below_floor`
- `nomis_employment` moved from `ok` to `below_floor`

## Completed Removal: Globally Constant Series

Every indexed sample for these dataset/series pairs was constant with the same
value. These series were removed from recipe build outputs, indexes, README
material statistics, manifests where present, and verification expectations.

| dataset_id | series_id | kind | samples | values | bytes | constant |
|---|---|---|---:|---:|---:|---|
| `arxiv_ai_recent` | `arxiv_ai_id_length` | `uint16` | 1 | 100 | 200 | `33` |
| `biorxiv_details` | `biorxiv_details_date` | `uint32` | 1 | 30 | 120 | `1704067200` |
| `biorxiv_details` | `biorxiv_details_version` | `uint16` | 1 | 30 | 60 | `1` |
| `chembl_molecules` | `chembl_black_box_warning` | `uint8` | 1 | 97 | 97 | `0` |
| `chembl_molecules` | `chembl_chirality` | `int16` | 1 | 97 | 194 | `-1` |
| `chembl_molecules` | `chembl_max_phase` | `uint8` | 1 | 97 | 97 | `0` |
| `chembl_molecules` | `chembl_oral` | `uint8` | 1 | 97 | 97 | `0` |
| `chembl_molecules` | `chembl_parenteral` | `uint8` | 1 | 97 | 97 | `0` |
| `chembl_molecules` | `chembl_topical` | `uint8` | 1 | 97 | 97 | `0` |
| `crossref_funders` | `crossref_replaced_by_count` | `uint16` | 1 | 100 | 200 | `0` |
| `datacite_dois` | `datacite_download_count` | `uint32` | 1 | 100 | 400 | `0` |
| `datacite_dois` | `datacite_view_count` | `uint32` | 1 | 100 | 400 | `0` |
| `dataone_solr` | `dataone_is_public` | `uint8` | 1 | 1000 | 1000 | `1` |
| `dataone_solr_large_retry` | `dataone_is_public` | `uint8` | 1 | 1000 | 1000 | `1` |
| `disease_sh_countries` | `disease_today_cases` | `uint32` | 1 | 231 | 924 | `0` |
| `disease_sh_countries` | `disease_today_deaths` | `uint32` | 1 | 231 | 924 | `0` |
| `dryad_search` | `dryad_citation_count` | `uint32` | 1 | 20 | 80 | `0` |
| `dryad_search` | `dryad_download_count` | `uint32` | 1 | 20 | 80 | `0` |
| `dryad_search` | `dryad_view_count` | `uint32` | 1 | 20 | 80 | `0` |
| `eia_series_petroleum` | `eia_petroleum_period_year` | `uint16` | 1 | 500 | 1000 | `2026` |
| `eia_series_petroleum` | `eia_petroleum_process_name_length` | `uint8` | 1 | 500 | 500 | `14` |
| `ena_portal_search` | `ena_collection_year_u16` | `uint16` | 1 | 500 | 1000 | `0` |
| `esco_occupations` | `esco_broader_group_count` | `uint16` | 1 | 71 | 142 | `1` |
| `esco_occupations` | `esco_preferred_label_count` | `uint16` | 1 | 71 | 142 | `28` |
| `esco_occupations` | `esco_scheme_count` | `uint16` | 1 | 71 | 142 | `2` |
| `expression_atlas_experiments` | `atlas_project_count_u16` | `uint16` | 1 | 4562 | 9124 | `0` |
| `federalregister_documents_large` | `fedreg_publication_month` | `uint8` | 1 | 1000 | 1000 | `12` |
| `federalregister_documents_large` | `fedreg_publication_year` | `uint16` | 1 | 1000 | 2000 | `2024` |
| `figshare_articles` | `figshare_created_year` | `uint16` | 1 | 100 | 200 | `2026` |
| `figshare_articles` | `figshare_published_year` | `uint16` | 1 | 100 | 200 | `2026` |
| `gbif_occurrence` | `gbif_month` | `uint8` | 1 | 100 | 100 | `1` |
| `gbif_occurrence` | `gbif_year` | `uint16` | 1 | 100 | 200 | `2026` |
| `gbif_occurrence_large` | `gbif_month` | `uint8` | 1 | 300 | 300 | `1` |
| `gbif_occurrence_large` | `gbif_year` | `uint16` | 1 | 300 | 600 | `2026` |
| `geoboundaries_all_adm0` | `geoboundaries_adm_unit_count` | `uint16` | 1 | 230 | 460 | `1` |
| `gitlab_projects` | `gitlab_forks_count` | `uint32` | 1 | 100 | 400 | `0` |
| `gitlab_projects` | `gitlab_star_count` | `uint32` | 1 | 100 | 400 | `0` |
| `gleif_lei_records` | `gleif_initial_registration_year` | `uint16` | 1 | 100 | 200 | `2026` |
| `gleif_lei_records` | `gleif_next_renewal_year` | `uint16` | 1 | 100 | 200 | `2027` |
| `gleif_lei_records_api` | `gleif_initial_registration_year_u16` | `uint16` | 1 | 200 | 400 | `2026` |
| `gleif_lei_records_api` | `gleif_next_renewal_year_u16` | `uint16` | 1 | 200 | 400 | `2027` |
| `gutendex_books` | `gutendex_copyright` | `uint8` | 1 | 32 | 32 | `0` |
| `gutendex_books` | `gutendex_language_count` | `uint8` | 1 | 32 | 32 | `1` |
| `gwas_catalog_studies` | `gwas_accession_length_u16` | `uint16` | 1 | 100 | 200 | `10` |
| `gwas_catalog_studies` | `gwas_genotyping_tech_count_u16` | `uint16` | 1 | 100 | 200 | `1` |
| `huggingface_datasets` | `hf_dataset_disabled` | `uint8` | 1 | 100 | 100 | `0` |
| `huggingface_datasets` | `hf_dataset_private` | `uint8` | 1 | 100 | 100 | `0` |
| `huggingface_models_large` | `hf_model_private` | `uint8` | 1 | 500 | 500 | `0` |
| `internetarchive_advancedsearch` | `ia_week` | `uint16` | 1 | 500 | 1000 | `0` |
| `launchlibrary_upcoming` | `launchlib_webcast_live` | `uint8` | 1 | 100 | 100 | `0` |
| `library_of_congress_items` | `loc_resource_count` | `uint16` | 1 | 44 | 88 | `1` |
| `metacpan_releases_search_large` | `metacpan_license_count` | `uint8` | 1 | 1000 | 1000 | `1` |
| `musicbrainz_recordings` | `musicbrainz_video_flag` | `uint8` | 1 | 94 | 94 | `0` |
| `nasa_donki_cme` | `donki_cme_begin_year_u16` | `uint16` | 1 | 1512 | 3024 | `2024` |
| `nasa_donki_flr` | `donki_flr_begin_year` | `uint16` | 1 | 1128 | 2256 | `2024` |
| `nasa_donki_flr` | `donki_flr_end_year` | `uint16` | 1 | 1128 | 2256 | `2024` |
| `nasa_donki_flr` | `donki_flr_instrument_count` | `uint8` | 1 | 1128 | 1128 | `1` |
| `nasa_donki_flr` | `donki_flr_peak_year` | `uint16` | 1 | 1128 | 2256 | `2024` |
| `nasa_eonet_events` | `eonet_categories_count` | `uint8` | 1 | 6705 | 6705 | `1` |
| `nih_reporter_projects` | `nih_fiscal_year_u16` | `uint16` | 1 | 428 | 856 | `2024` |
| `noaa_tides_water_level` | `noaa_tides_month_u8` | `uint8` | 1 | 7440 | 7440 | `1` |
| `noaa_tides_water_level` | `noaa_tides_q_length_u8` | `uint8` | 1 | 7440 | 7440 | `1` |
| `noaa_tides_water_level` | `noaa_tides_year_u16` | `uint16` | 1 | 7440 | 14880 | `2024` |
| `nomis_employment` | `nomis_geography` | `uint32` | 1 | 1545 | 6180 | `2092957698` |
| `nomis_employment` | `nomis_item` | `uint8` | 1 | 1545 | 1545 | `1` |
| `nomis_employment` | `nomis_measure` | `uint32` | 1 | 1545 | 6180 | `20100` |
| `npm_search_packages_large` | `npm_insecure_flag` | `uint8` | 1 | 250 | 250 | `0` |
| `nuget_search` | `nuget_author_count` | `uint16` | 1 | 100 | 200 | `1` |
| `nuget_search` | `nuget_package_type_count` | `uint8` | 1 | 100 | 100 | `1` |
| `nvd_cpe_match_feed` | `nvd_cpe_created_at_u32` | `uint32` | 1 | 500 | 2000 | `1560762993` |
| `ooni_measurements` | `ooni_confirmed` | `uint8` | 1 | 100 | 100 | `0` |
| `ooni_measurements` | `ooni_failure` | `uint8` | 1 | 100 | 100 | `1` |
| `openalex_institutions_large` | `openalex_inst_topic_count` | `uint16` | 1 | 200 | 400 | `25` |
| `openalex_works_2024_sample` | `openalex_publication_year` | `uint16` | 1 | 200 | 400 | `2024` |
| `openfda_device_event` | `openfda_device_event_devices_in_event_u16` | `uint16` | 1 | 500 | 1000 | `0` |
| `openfda_device_event` | `openfda_device_event_patients_in_event_u16` | `uint16` | 1 | 500 | 1000 | `0` |
| `osf_preprints` | `osf_public` | `uint8` | 1 | 100 | 100 | `1` |
| `pride_projects_search` | `pride_project_avg_downloads_per_file_f32` | `float32` | 1 | 100 | 400 | `0.0` |
| `pride_projects_search` | `pride_project_download_count_u32` | `uint32` | 1 | 100 | 400 | `0` |
| `pride_projects_search` | `pride_project_labpi_count_u16` | `uint16` | 1 | 100 | 200 | `1` |
| `pride_projects_search` | `pride_project_percentile_f32` | `float32` | 1 | 100 | 400 | `0.0` |
| `pride_projects_search` | `pride_project_submitter_count_u16` | `uint16` | 1 | 100 | 200 | `1` |
| `scryfall_cards` | `scryfall_multiverse_id_count` | `uint8` | 1 | 164 | 164 | `1` |
| `scryfall_default_cards` | `scryfall_released_year_u16` | `uint16` | 1 | 175 | 350 | `2026` |
| `steamspy_top100in2weeks` | `steamspy_average_forever` | `uint32` | 1 | 100 | 400 | `0` |
| `steamspy_top100in2weeks` | `steamspy_userscore` | `uint16` | 1 | 100 | 200 | `0` |
| `treasury_avg_interest_rates` | `treasury_record_fiscal_year` | `uint16` | 1 | 100 | 200 | `2026` |
| `usgs_sitefile_all_large` | `usgs_state_cd_u16` | `uint16` | 1 | 90404 | 180808 | `6` |
| `worldbank_gdp_constant` | `worldbank_gdp_country_iso_length_u8` | `uint8` | 1 | 190 | 190 | `3` |
| `worldbank_gdp_constant` | `worldbank_gdp_decimal_u8` | `uint8` | 1 | 190 | 190 | `0` |
| `worldbank_gdp_constant` | `worldbank_gdp_indicator_name_length_u8` | `uint8` | 1 | 190 | 190 | `23` |
| `worldbank_population_total` | `worldbank_population_country_iso_length_u8` | `uint8` | 1 | 196 | 196 | `3` |
| `worldbank_population_total` | `worldbank_population_decimal_u8` | `uint8` | 1 | 196 | 196 | `0` |
| `worldbank_population_total` | `worldbank_population_indicator_name_length_u8` | `uint8` | 1 | 196 | 196 | `17` |

## Filter Target: Constant Samples Inside Non-Constant Series

These are not whole-series removals. The listed series contains useful
non-constant samples, but some indexed samples are constant and should be
filtered at build time or rejected by verify.

| dataset_id | series_id | kind | constant samples | constant values / total values | constant values seen |
|---|---|---|---:|---:|---|
| `noaa_ghcn_daily_snwd_by_station` | `ghcn_value_i16` | `int16` | 1 / 59 | 28251 / 1754123 | `0` |
| `noaa_ghcn_daily_tsun_by_station` | `ghcn_value_i16` | `int16` | 27 / 43 | 26591 / 159967 | `0 (26), 708` |
| `noaa_ghcn_daily_wesd_by_station` | `ghcn_value_i16` | `int16` | 4 / 28 | 400 / 102894 | `0, 10455, 10531, 5288` |
| `noaa_ghcn_daily_wsfg_by_station` | `ghcn_value_i16` | `int16` | 7 / 40 | 8 / 266486 | `0 (2), 192, 438, 62, 80, 89` |
| `noaa_isd_lite` | `isd_precip1h` | `int16` | 30 / 46 | 683226 / 1098311 | `-9999 (30)` |
| `noaa_isd_lite` | `isd_precip6h` | `int16` | 11 / 46 | 214314 / 1098311 | `-9999 (11)` |
| `noaa_isd_lite` | `isd_sky` | `int16` | 3 / 46 | 31180 / 1098311 | `-9999 (3)` |
| `noaa_isd_lite` | `isd_slp` | `int16` | 5 / 46 | 129773 / 1098311 | `-9999 (5)` |
| `noaa_isd_lite` | `isd_wspd` | `int16` | 1 / 46 | 17535 / 1098311 | `-9999` |
| `world_bank_access_to_electricity_percent_annual` | `access_to_electricity_percent_f64` | `float64` | 4 / 10 | 136 / 319 | `100.0 (4)` |

## Explicit Non-Scope

Do not use this report to remove sparse-binary findings. Those remain in
`reports/degenerate_series_audit.tsv` and should be handled in a later pass
with their own justification and policy.
