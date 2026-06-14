# Dataset State Report

Acceptance floor used by this report: at least `10000` primary values, at least `102400` primary bytes, median primary sample size at least `1000` values, and primary output at most `1000000000` bytes.

## `geofabrik_liechtenstein_osm_pbf_u8`

- status: `ok`
- reasons: `none`
- primary_samples: 52
- primary_values: 7809486
- primary_bytes: 7809486
- primary_value_count_range: 39195 / 102373.5 / 688184 min/median/max
- primary_size_range_bytes: 39195 / 102373.5 / 688184 min/median/max
- primary_size_distribution_bytes: 39195 / 87686.9 / 94500.5 / 102373.5 / 113444.8 / 400242.0 / 688184 min/p10/p25/median/p75/p90/max
- primary_same_size_fraction: 0.019231

| series_id | role | kind | width | samples | values | bytes | value distribution min/p10/p25/median/p75/p90/max | byte distribution min/p10/p25/median/p75/p90/max | same-size fraction | missing files |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `osm_pbf_primitive_blocks` | primary | uint | 8 | 52 | 7809486 | 7809486 | 39195 / 87686.9 / 94500.5 / 102373.5 / 113444.8 / 400242.0 / 688184 | 39195 / 87686.9 / 94500.5 / 102373.5 / 113444.8 / 400242.0 / 688184 | 0.019231 | 0 |

## `ncbi_refseq_viral_genomes_u8`

- status: `ok`
- reasons: `none`
- primary_samples: 19433
- primary_values: 577707132
- primary_bytes: 577707132
- primary_value_count_range: 136 / 6864 / 2473870 min/median/max
- primary_size_range_bytes: 136 / 6864 / 2473870 min/median/max
- primary_size_distribution_bytes: 136 / 1707 / 2750 / 6864 / 39989 / 73739.4 / 2473870 min/p10/p25/median/p75/p90/max
- primary_same_size_fraction: 0.000772

| series_id | role | kind | width | samples | values | bytes | value distribution min/p10/p25/median/p75/p90/max | byte distribution min/p10/p25/median/p75/p90/max | same-size fraction | missing files |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `refseq_viral_genome_bases` | primary | uint | 8 | 19433 | 577707132 | 577707132 | 136 / 1707 / 2750 / 6864 / 39989 / 73739.4 / 2473870 | 136 / 1707 / 2750 / 6864 / 39989 / 73739.4 / 2473870 | 0.000772 | 0 |
