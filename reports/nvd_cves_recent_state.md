# Dataset State Report

Acceptance floor used by this report: at least `10000` primary values, at least `102400` primary bytes, median primary sample size at least `1000` values, and primary output at most `1000000000` bytes.

## `nvd_cves_recent`

- status: `ok`
- reasons: `none`
- primary_samples: 6
- primary_values: 244224
- primary_bytes: 651264
- primary_value_count_range: 40704 / 40704 / 40704 min/median/max
- primary_size_range_bytes: 81408 / 81408 / 162816 min/median/max
- primary_size_distribution_bytes: 81408 / 81408 / 81408 / 81408 / 142464 / 162816 / 162816 min/p10/p25/median/p75/p90/max
- primary_same_size_fraction: 0.666667

| series_id | role | kind | width | samples | values | bytes | value distribution min/p10/p25/median/p75/p90/max | byte distribution min/p10/p25/median/p75/p90/max | same-size fraction | missing files |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `nvd_cpe_match_count` | primary | uint | 16 | 1 | 40704 | 81408 | 40704 / 40704 / 40704 / 40704 / 40704 / 40704 / 40704 | 81408 / 81408 / 81408 / 81408 / 81408 / 81408 / 81408 | 1.000000 | 0 |
| `nvd_cvss_base_score_x10` | primary | uint | 16 | 1 | 40704 | 81408 | 40704 / 40704 / 40704 / 40704 / 40704 / 40704 / 40704 | 81408 / 81408 / 81408 / 81408 / 81408 / 81408 / 81408 | 1.000000 | 0 |
| `nvd_last_modified_at` | primary | uint | 32 | 1 | 40704 | 162816 | 40704 / 40704 / 40704 / 40704 / 40704 / 40704 / 40704 | 162816 / 162816 / 162816 / 162816 / 162816 / 162816 / 162816 | 1.000000 | 0 |
| `nvd_primary_cwe_id` | primary | uint | 16 | 1 | 40704 | 81408 | 40704 / 40704 / 40704 / 40704 / 40704 / 40704 / 40704 | 81408 / 81408 / 81408 / 81408 / 81408 / 81408 / 81408 | 1.000000 | 0 |
| `nvd_published_at` | primary | uint | 32 | 1 | 40704 | 162816 | 40704 / 40704 / 40704 / 40704 / 40704 / 40704 / 40704 | 162816 / 162816 / 162816 / 162816 / 162816 / 162816 / 162816 | 1.000000 | 0 |
| `nvd_reference_count` | primary | uint | 16 | 1 | 40704 | 81408 | 40704 / 40704 / 40704 / 40704 / 40704 / 40704 / 40704 | 81408 / 81408 / 81408 / 81408 / 81408 / 81408 / 81408 | 1.000000 | 0 |
