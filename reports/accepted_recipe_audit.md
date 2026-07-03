# Accepted Recipe Audit

Acceptance floor: at least `10000` primary values total or at least `102400` primary sample bytes, plus median primary sample size at least `1000` values.

Auxiliary series do not count toward acceptance.

- `ok`: 216
- `below_floor`: 15
- `broken`: 0

## Below Floor

| dataset_id | primary_values | primary_sample_bytes | primary_sample_rows | median_primary_sample_value_count | auxiliary_values | auxiliary_sample_rows | reasons |
|---|---:|---:|---:|---:|---:|---:|---|
| `pride_projects_search` | 500 | 1600 | 5 | 100 | 0 | 0 | `aggregate_floor,median_sample_floor` |
| `gwas_catalog_studies` | 800 | 2200 | 8 | 100 | 0 | 0 | `aggregate_floor,median_sample_floor` |
| `ena_portal_search` | 1000 | 5000 | 2 | 500 | 0 | 0 | `aggregate_floor,median_sample_floor` |
| `iris_seismon_events_fixed` | 1170 | 5330 | 9 | 130 | 0 | 0 | `aggregate_floor,median_sample_floor` |
| `plos_search` | 1500 | 3500 | 3 | 500 | 0 | 0 | `aggregate_floor,median_sample_floor` |
| `coinpaprika_exchanges` | 1530 | 5760 | 6 | 255 | 0 | 0 | `aggregate_floor,median_sample_floor` |
| `europepmc_grants` | 1984 | 3968 | 4 | 496 | 0 | 0 | `aggregate_floor,median_sample_floor` |
| `chembl_documents` | 2000 | 4000 | 4 | 500 | 0 | 0 | `aggregate_floor,median_sample_floor` |
| `wikimedia_mostread` | 2000 | 6000 | 2 | 1000 | 0 | 0 | `aggregate_floor` |
| `npi_registry_ca` | 2000 | 7000 | 4 | 500 | 0 | 0 | `aggregate_floor,median_sample_floor` |
| `geofabrik_index` | 2220 | 17760 | 4 | 555 | 0 | 0 | `aggregate_floor,median_sample_floor` |
| `openfda_food_enforcement` | 2500 | 7500 | 5 | 500 | 0 | 0 | `aggregate_floor,median_sample_floor` |
| `loc_photos_search_large` | 3500 | 8000 | 7 | 500 | 0 | 0 | `aggregate_floor,median_sample_floor` |
| `smithsonian_search_large` | 3500 | 10000 | 7 | 500 | 0 | 0 | `aggregate_floor,median_sample_floor` |
| `crossref_funders_large` | 5000 | 10000 | 5 | 1000 | 0 | 0 | `aggregate_floor` |
