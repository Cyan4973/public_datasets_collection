# Dataset State Report

Acceptance floor used by this report: at least `10000` primary values, at least `102400` primary bytes, median primary sample size at least `1000` values, and primary output at most `1000000000` bytes.

## `census_acs_pums_ca_person_2023_i64`

- status: `ok`
- reasons: `none`
- primary_samples: 4
- primary_values: 1265252
- primary_bytes: 10122016
- primary_value_count_range: 204382 / 334276 / 392318 min/median/max
- primary_size_range_bytes: 1635056 / 2674208 / 3138544 min/median/max
- primary_size_distribution_bytes: 1635056 / 1946801.6 / 2414420 / 2674208 / 2790292 / 2999243.2 / 3138544 min/p10/p25/median/p75/p90/max
- primary_same_size_fraction: 0.500000

| series_id | role | kind | width | samples | values | bytes | value distribution min/p10/p25/median/p75/p90/max | byte distribution min/p10/p25/median/p75/p90/max | same-size fraction | missing files |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `person_weight_i64` | primary | int | 64 | 1 | 392318 | 3138544 | 392318 / 392318 / 392318 / 392318 / 392318 / 392318 / 392318 | 3138544 / 3138544 / 3138544 / 3138544 / 3138544 / 3138544 / 3138544 | 1.000000 | 0 |
| `personal_income_i64` | primary | int | 64 | 1 | 334276 | 2674208 | 334276 / 334276 / 334276 / 334276 / 334276 / 334276 / 334276 | 2674208 / 2674208 / 2674208 / 2674208 / 2674208 / 2674208 / 2674208 | 1.000000 | 0 |
| `wage_income_i64` | primary | int | 64 | 1 | 334276 | 2674208 | 334276 / 334276 / 334276 / 334276 / 334276 / 334276 / 334276 | 2674208 / 2674208 / 2674208 / 2674208 / 2674208 / 2674208 / 2674208 | 1.000000 | 0 |
| `weeks_worked_i64` | primary | int | 64 | 1 | 204382 | 1635056 | 204382 / 204382 / 204382 / 204382 / 204382 / 204382 / 204382 | 1635056 / 1635056 / 1635056 / 1635056 / 1635056 / 1635056 / 1635056 | 1.000000 | 0 |

## `citibike_2024_01_trip_geocoords_f64`

- status: `ok`
- reasons: `none`
- primary_samples: 8
- primary_values: 7527984
- primary_bytes: 60223872
- primary_value_count_range: 885384 / 940998 / 996612 min/median/max
- primary_size_range_bytes: 7083072 / 7527984 / 7972896 min/median/max
- primary_size_distribution_bytes: 7083072 / 7083072 / 7083072 / 7527984 / 7972896 / 7972896 / 7972896 min/p10/p25/median/p75/p90/max
- primary_same_size_fraction: 0.500000

| series_id | role | kind | width | samples | values | bytes | value distribution min/p10/p25/median/p75/p90/max | byte distribution min/p10/p25/median/p75/p90/max | same-size fraction | missing files |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `end_latitude_f64` | primary | float | 64 | 2 | 1881996 | 15055968 | 885384 / 896506.8 / 913191 / 940998 / 968805 / 985489.2 / 996612 | 7083072 / 7172054.4 / 7305528 / 7527984 / 7750440 / 7883913.6 / 7972896 | 0.500000 | 0 |
| `end_longitude_f64` | primary | float | 64 | 2 | 1881996 | 15055968 | 885384 / 896506.8 / 913191 / 940998 / 968805 / 985489.2 / 996612 | 7083072 / 7172054.4 / 7305528 / 7527984 / 7750440 / 7883913.6 / 7972896 | 0.500000 | 0 |
| `start_latitude_f64` | primary | float | 64 | 2 | 1881996 | 15055968 | 885384 / 896506.8 / 913191 / 940998 / 968805 / 985489.2 / 996612 | 7083072 / 7172054.4 / 7305528 / 7527984 / 7750440 / 7883913.6 / 7972896 | 0.500000 | 0 |
| `start_longitude_f64` | primary | float | 64 | 2 | 1881996 | 15055968 | 885384 / 896506.8 / 913191 / 940998 / 968805 / 985489.2 / 996612 | 7083072 / 7172054.4 / 7305528 / 7527984 / 7750440 / 7883913.6 / 7972896 | 0.500000 | 0 |

## `sec_fsd_2024q1_q4_numeric_values_i64`

- status: `ok`
- reasons: `none`
- primary_samples: 8
- primary_values: 11808107
- primary_bytes: 94464856
- primary_value_count_range: 216070 / 1379016.5 / 2892132 min/median/max
- primary_size_range_bytes: 1728560 / 11032132 / 23137056 min/median/max
- primary_size_distribution_bytes: 1728560 / 1856693.6 / 1963364 / 11032132 / 21674316 / 22421964 / 23137056 min/p10/p25/median/p75/p90/max
- primary_same_size_fraction: 0.125000

| series_id | role | kind | width | samples | values | bytes | value distribution min/p10/p25/median/p75/p90/max | byte distribution min/p10/p25/median/p75/p90/max | same-size fraction | missing files |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `shares_value_i64` | primary | int | 64 | 4 | 972821 | 7782568 | 216070 / 222934.3 / 233230.8 / 243264 / 253238.5 / 263429.2 / 270223 | 1728560 / 1783474.4 / 1865846 / 1946112 / 2025908 / 2107433.6 / 2161784 | 0.250000 | 0 |
| `usd_value_i64` | primary | int | 64 | 4 | 10835286 | 86682288 | 2487810 / 2548739.1 / 2640132.8 / 2727672 / 2796360.8 / 2853823.5 / 2892132 | 19902480 / 20389912.8 / 21121062 / 21821376 / 22370886 / 22830588 / 23137056 | 0.250000 | 0 |

