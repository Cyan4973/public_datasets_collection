# NOAA NDBC Wave Spectral Density Material Report

Dataset: `noaa_ndbc_wave_spectral_density_f64`

Status: accepted after local download, build, and verification.

## Source

- source: NOAA National Data Buoy Center historical `swden` spectral wave density archive
- license: U.S. Government public domain
- selected subset: 8 buoy stations x 3 years, 2021-2023
- downloaded resources: 24 gzip-compressed text files
- source bytes: 13,558,316
- source data rows retained: 249,347 / 249,347
- rejected rows: 0 malformed, 0 NDBC missing-sentinel, 0 short rows

## Output

- natural sample boundary: one station-year spectral density grid
- primary series: `wave_spectral_density`
- numeric representation: little-endian float64
- geometry: 2D grid with axes `time` x `frequency_hz`
- frequency bins per sample: 47
- primary samples: 24
- primary values: 11,719,309
- primary bytes: 93,754,472
- value count distribution: 106,690 / 207,368.7 / 402,237.8 / 427,159.5 / 639,482 / 817,588.5 / 819,586 min/p10/p25/median/p75/p90/max
- byte distribution: 853,520 / 1,658,949.6 / 3,217,902 / 3,417,276 / 5,115,856 / 6,540,708 / 6,556,688 min/p10/p25/median/p75/p90/max
- same-size fraction: 0.041667

## Sample Inventory

| station | year | rows | freq bins | values | bytes |
|---|---:|---:|---:|---:|---:|
| `41002` | 2021 | 4942 | 47 | 232274 | 1858192 |
| `41002` | 2022 | 9071 | 47 | 426337 | 3410696 |
| `41002` | 2023 | 17438 | 47 | 819586 | 6556688 |
| `41004` | 2021 | 4185 | 47 | 196695 | 1573560 |
| `41004` | 2022 | 9901 | 47 | 465347 | 3722776 |
| `41004` | 2023 | 17427 | 47 | 819069 | 6552552 |
| `42001` | 2021 | 2270 | 47 | 106690 | 853520 |
| `42001` | 2022 | 3826 | 47 | 179822 | 1438576 |
| `42001` | 2023 | 17322 | 47 | 814134 | 6513072 |
| `42002` | 2021 | 8564 | 47 | 402508 | 3220064 |
| `42002` | 2022 | 9233 | 47 | 433951 | 3471608 |
| `42002` | 2023 | 17436 | 47 | 819492 | 6555936 |
| `46002` | 2021 | 8581 | 47 | 403307 | 3226456 |
| `46002` | 2022 | 9074 | 47 | 426478 | 3411824 |
| `46002` | 2023 | 12735 | 47 | 598545 | 4788360 |
| `46042` | 2021 | 8541 | 47 | 401427 | 3211416 |
| `46042` | 2022 | 8977 | 47 | 421919 | 3375352 |
| `46042` | 2023 | 12585 | 47 | 591495 | 4731960 |
| `46047` | 2021 | 8573 | 47 | 402931 | 3223448 |
| `46047` | 2022 | 9409 | 47 | 442223 | 3537784 |
| `46047` | 2023 | 16219 | 47 | 762293 | 6098344 |
| `51001` | 2021 | 6636 | 47 | 311892 | 2495136 |
| `51001` | 2022 | 9103 | 47 | 427841 | 3422728 |
| `51001` | 2023 | 17299 | 47 | 813053 | 6504424 |

## Notes

This is a NOAA dataset, but not the already-saturated scalar station-weather
shape. The retained samples are dense spectral grids over native NDBC frequency
bins. Sample sizes vary by station and year because buoy reporting coverage
varies.
