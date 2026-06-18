# Dataset State Report

Acceptance floor used by this generic report: at least `10000` primary values,
at least `102400` primary bytes, median primary sample size at least `1000`
values, and primary output at most `1000000000` bytes.

Note: for `citibike_2024_trip_geocoords_f64`, the 1 GB threshold is an explicit
soft warning and the recipe uses a 2 GB hard guard. The `primary_size_cap`
reason below records this soft-cap exceedance, not a validation failure.

## `citibike_2024_trip_geocoords_f64`

- status: `needs_attention`
- reasons: `primary_size_cap`
- primary_samples: 200
- primary_values: 176663392
- primary_bytes: 1413307136
- primary_value_count_range: 121445 / 995688.5 / 999613 min/median/max
- primary_size_range_bytes: 971560 / 7965508 / 7996904 min/median/max
- primary_size_distribution_bytes: 971560 / 4592647.2 / 7941328 / 7965508 / 7988952 / 7995863.2 / 7996904 min/p10/p25/median/p75/p90/max
- primary_same_size_fraction: 0.040000

| series_id | role | kind | width | samples | values | bytes | value distribution min/p10/p25/median/p75/p90/max | byte distribution min/p10/p25/median/p75/p90/max | same-size fraction | missing files |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `end_latitude_f64` | primary | float | 64 | 50 | 44165848 | 353326784 | 121445 / 574080.9 / 992686.8 / 995688.5 / 998520.2 / 999482.9 / 999613 | 971560 / 4592647.2 / 7941494 / 7965508 / 7988162 / 7995863.2 / 7996904 | 0.040000 | 0 |
| `end_longitude_f64` | primary | float | 64 | 50 | 44165848 | 353326784 | 121445 / 574080.9 / 992686.8 / 995688.5 / 998520.2 / 999482.9 / 999613 | 971560 / 4592647.2 / 7941494 / 7965508 / 7988162 / 7995863.2 / 7996904 | 0.040000 | 0 |
| `start_latitude_f64` | primary | float | 64 | 50 | 44165848 | 353326784 | 121445 / 574080.9 / 992686.8 / 995688.5 / 998520.2 / 999482.9 / 999613 | 971560 / 4592647.2 / 7941494 / 7965508 / 7988162 / 7995863.2 / 7996904 | 0.040000 | 0 |
| `start_longitude_f64` | primary | float | 64 | 50 | 44165848 | 353326784 | 121445 / 574080.9 / 992686.8 / 995688.5 / 998520.2 / 999482.9 / 999613 | 971560 / 4592647.2 / 7941494 / 7965508 / 7988162 / 7995863.2 / 7996904 | 0.040000 | 0 |
