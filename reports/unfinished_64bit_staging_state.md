# Dataset State Report

Acceptance floor used by this report: at least `10000` primary values, at least `102400` primary bytes, median primary sample size at least `1000` values, and primary output at most `1000000000` bytes.

## `ena_runs_portal`

- status: `needs_attention`
- reasons: `value_floor,byte_floor,median_sample_floor`
- primary_samples: 6
- primary_values: 3000
- primary_bytes: 9000
- primary_value_count_range: 500 / 500 / 500 min/median/max
- primary_size_range_bytes: 500 / 1000 / 4000 min/median/max
- primary_size_distribution_bytes: 500 / 500 / 625 / 1000 / 1750 / 3000 / 4000 min/p10/p25/median/p75/p90/max
- primary_same_size_fraction: 0.333333

| series_id | role | kind | width | samples | values | bytes | value distribution min/p10/p25/median/p75/p90/max | byte distribution min/p10/p25/median/p75/p90/max | same-size fraction | missing files |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `ena_base_count_u64` | primary | uint | 64 | 1 | 500 | 4000 | 500 / 500 / 500 / 500 / 500 / 500 / 500 | 4000 / 4000 / 4000 / 4000 / 4000 / 4000 / 4000 | 1.000000 | 0 |
| `ena_collection_date_length_u8` | primary | uint | 8 | 1 | 500 | 500 | 500 / 500 / 500 / 500 / 500 / 500 / 500 | 500 / 500 / 500 / 500 / 500 / 500 / 500 | 1.000000 | 0 |
| `ena_country_length_u8` | primary | uint | 8 | 1 | 500 | 500 | 500 / 500 / 500 / 500 / 500 / 500 / 500 | 500 / 500 / 500 / 500 / 500 / 500 / 500 | 1.000000 | 0 |
| `ena_read_count_u32` | primary | uint | 32 | 1 | 500 | 2000 | 500 / 500 / 500 / 500 / 500 / 500 / 500 | 2000 / 2000 / 2000 / 2000 / 2000 / 2000 / 2000 | 1.000000 | 0 |
| `ena_run_accession_length_u16` | primary | uint | 16 | 1 | 500 | 1000 | 500 / 500 / 500 / 500 / 500 / 500 / 500 | 1000 / 1000 / 1000 / 1000 / 1000 / 1000 / 1000 | 1.000000 | 0 |
| `ena_scientific_name_length_u16` | primary | uint | 16 | 1 | 500 | 1000 | 500 / 500 / 500 / 500 / 500 / 500 / 500 | 1000 / 1000 / 1000 / 1000 / 1000 / 1000 / 1000 | 1.000000 | 0 |

## `sec_companyfacts_core_financials_quarterly`

- status: `needs_attention`
- reasons: `value_floor,byte_floor,median_sample_floor`
- primary_samples: 25
- primary_values: 1135
- primary_bytes: 9080
- primary_value_count_range: 32 / 51 / 51 min/median/max
- primary_size_range_bytes: 256 / 408 / 408 min/median/max
- primary_size_distribution_bytes: 256 / 256 / 336 / 408 / 408 / 408 / 408 min/p10/p25/median/p75/p90/max
- primary_same_size_fraction: 0.600000

| series_id | role | kind | width | samples | values | bytes | value distribution min/p10/p25/median/p75/p90/max | byte distribution min/p10/p25/median/p75/p90/max | same-size fraction | missing files |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `assets_i64` | primary | int | 64 | 5 | 227 | 1816 | 32 / 36 / 42 / 51 / 51 / 51 / 51 | 256 / 288 / 336 / 408 / 408 / 408 / 408 | 0.600000 | 0 |
| `cash_and_equivalents_i64` | primary | int | 64 | 5 | 227 | 1816 | 32 / 36 / 42 / 51 / 51 / 51 / 51 | 256 / 288 / 336 / 408 / 408 / 408 / 408 | 0.600000 | 0 |
| `net_income_i64` | primary | int | 64 | 5 | 227 | 1816 | 32 / 36 / 42 / 51 / 51 / 51 / 51 | 256 / 288 / 336 / 408 / 408 / 408 / 408 | 0.600000 | 0 |
| `operating_income_i64` | primary | int | 64 | 5 | 227 | 1816 | 32 / 36 / 42 / 51 / 51 / 51 / 51 | 256 / 288 / 336 / 408 / 408 / 408 / 408 | 0.600000 | 0 |
| `stockholders_equity_i64` | primary | int | 64 | 5 | 227 | 1816 | 32 / 36 / 42 / 51 / 51 / 51 / 51 | 256 / 288 / 336 / 408 / 408 / 408 / 408 | 0.600000 | 0 |

## `sec_submissions_nvda`

- status: `needs_attention`
- reasons: `value_floor,byte_floor`
- primary_samples: 5
- primary_values: 5010
- primary_bytes: 16032
- primary_value_count_range: 1002 / 1002 / 1002 min/median/max
- primary_size_range_bytes: 1002 / 2004 / 8016 min/median/max
- primary_size_distribution_bytes: 1002 / 1002 / 1002 / 2004 / 4008 / 6412.8 / 8016 min/p10/p25/median/p75/p90/max
- primary_same_size_fraction: 0.400000

| series_id | role | kind | width | samples | values | bytes | value distribution min/p10/p25/median/p75/p90/max | byte distribution min/p10/p25/median/p75/p90/max | same-size fraction | missing files |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `sec_nvda_acceptance_timestamp` | primary | uint | 64 | 1 | 1002 | 8016 | 1002 / 1002 / 1002 / 1002 / 1002 / 1002 / 1002 | 8016 / 8016 / 8016 / 8016 / 8016 / 8016 / 8016 | 1.000000 | 0 |
| `sec_nvda_filing_day` | primary | uint | 8 | 1 | 1002 | 1002 | 1002 / 1002 / 1002 / 1002 / 1002 / 1002 / 1002 | 1002 / 1002 / 1002 / 1002 / 1002 / 1002 / 1002 | 1.000000 | 0 |
| `sec_nvda_filing_month` | primary | uint | 8 | 1 | 1002 | 1002 | 1002 / 1002 / 1002 / 1002 / 1002 / 1002 / 1002 | 1002 / 1002 / 1002 / 1002 / 1002 / 1002 / 1002 | 1.000000 | 0 |
| `sec_nvda_filing_year` | primary | uint | 16 | 1 | 1002 | 2004 | 1002 / 1002 / 1002 / 1002 / 1002 / 1002 / 1002 | 2004 / 2004 / 2004 / 2004 / 2004 / 2004 / 2004 | 1.000000 | 0 |
| `sec_nvda_submission_size` | primary | uint | 32 | 1 | 1002 | 4008 | 1002 / 1002 / 1002 / 1002 / 1002 / 1002 / 1002 | 4008 / 4008 / 4008 / 4008 / 4008 / 4008 / 4008 | 1.000000 | 0 |

## `sec_submissions_tsla`

- status: `needs_attention`
- reasons: `value_floor,byte_floor`
- primary_samples: 5
- primary_values: 5005
- primary_bytes: 16016
- primary_value_count_range: 1001 / 1001 / 1001 min/median/max
- primary_size_range_bytes: 1001 / 2002 / 8008 min/median/max
- primary_size_distribution_bytes: 1001 / 1001 / 1001 / 2002 / 4004 / 6406.4 / 8008 min/p10/p25/median/p75/p90/max
- primary_same_size_fraction: 0.400000

| series_id | role | kind | width | samples | values | bytes | value distribution min/p10/p25/median/p75/p90/max | byte distribution min/p10/p25/median/p75/p90/max | same-size fraction | missing files |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `sec_tsla_acceptance_timestamp` | primary | uint | 64 | 1 | 1001 | 8008 | 1001 / 1001 / 1001 / 1001 / 1001 / 1001 / 1001 | 8008 / 8008 / 8008 / 8008 / 8008 / 8008 / 8008 | 1.000000 | 0 |
| `sec_tsla_filing_day` | primary | uint | 8 | 1 | 1001 | 1001 | 1001 / 1001 / 1001 / 1001 / 1001 / 1001 / 1001 | 1001 / 1001 / 1001 / 1001 / 1001 / 1001 / 1001 | 1.000000 | 0 |
| `sec_tsla_filing_month` | primary | uint | 8 | 1 | 1001 | 1001 | 1001 / 1001 / 1001 / 1001 / 1001 / 1001 / 1001 | 1001 / 1001 / 1001 / 1001 / 1001 / 1001 / 1001 | 1.000000 | 0 |
| `sec_tsla_filing_year` | primary | uint | 16 | 1 | 1001 | 2002 | 1001 / 1001 / 1001 / 1001 / 1001 / 1001 / 1001 | 2002 / 2002 / 2002 / 2002 / 2002 / 2002 / 2002 | 1.000000 | 0 |
| `sec_tsla_submission_size` | primary | uint | 32 | 1 | 1001 | 4004 | 1001 / 1001 / 1001 / 1001 / 1001 / 1001 / 1001 | 4004 / 4004 / 4004 / 4004 / 4004 / 4004 / 4004 | 1.000000 | 0 |

## `usgs_water_current`

- status: `ok`
- reasons: `none`
- primary_samples: 7
- primary_values: 60375
- primary_bytes: 129375
- primary_value_count_range: 8625 / 8625 / 8625 min/median/max
- primary_size_range_bytes: 8625 / 8625 / 69000 min/median/max
- primary_size_distribution_bytes: 8625 / 8625 / 8625 / 8625 / 12937.5 / 37950.0 / 69000 min/p10/p25/median/p75/p90/max
- primary_same_size_fraction: 0.714286

| series_id | role | kind | width | samples | values | bytes | value distribution min/p10/p25/median/p75/p90/max | byte distribution min/p10/p25/median/p75/p90/max | same-size fraction | missing files |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `usgs_water_current_day_u8` | primary | uint | 8 | 1 | 8625 | 8625 | 8625 / 8625 / 8625 / 8625 / 8625 / 8625 / 8625 | 8625 / 8625 / 8625 / 8625 / 8625 / 8625 / 8625 | 1.000000 | 0 |
| `usgs_water_current_hour_u8` | primary | uint | 8 | 1 | 8625 | 8625 | 8625 / 8625 / 8625 / 8625 / 8625 / 8625 / 8625 | 8625 / 8625 / 8625 / 8625 / 8625 / 8625 / 8625 | 1.000000 | 0 |
| `usgs_water_current_minute_u8` | primary | uint | 8 | 1 | 8625 | 8625 | 8625 / 8625 / 8625 / 8625 / 8625 / 8625 / 8625 | 8625 / 8625 / 8625 / 8625 / 8625 / 8625 / 8625 | 1.000000 | 0 |
| `usgs_water_current_month_u8` | primary | uint | 8 | 1 | 8625 | 8625 | 8625 / 8625 / 8625 / 8625 / 8625 / 8625 / 8625 | 8625 / 8625 / 8625 / 8625 / 8625 / 8625 / 8625 | 1.000000 | 0 |
| `usgs_water_current_qualifier_count_u8` | primary | uint | 8 | 1 | 8625 | 8625 | 8625 / 8625 / 8625 / 8625 / 8625 / 8625 / 8625 | 8625 / 8625 / 8625 / 8625 / 8625 / 8625 / 8625 | 1.000000 | 0 |
| `usgs_water_current_value_f64` | primary | float | 64 | 1 | 8625 | 69000 | 8625 / 8625 / 8625 / 8625 / 8625 / 8625 / 8625 | 69000 / 69000 / 69000 / 69000 / 69000 / 69000 / 69000 | 1.000000 | 0 |
| `usgs_water_current_year_u16` | primary | uint | 16 | 1 | 8625 | 17250 | 8625 / 8625 / 8625 / 8625 / 8625 / 8625 / 8625 | 17250 / 17250 / 17250 / 17250 / 17250 / 17250 / 17250 | 1.000000 | 0 |

