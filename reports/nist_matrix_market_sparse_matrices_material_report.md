# NIST Matrix Market Sparse Matrices Material Report

Dataset: `nist_matrix_market_sparse_matrices`

Status: accepted after local download, build, duplicate filtering, and
verification.

## Source

- source: NIST Matrix Market, Harwell-Boeing `bcsstk` structural matrices
- license: U.S. Government public domain
- candidate URLs: `bcsstk01` through `bcsstk24`
- download-retained resources: 21 Matrix Market `.mtx.gz` files
- built unique matrices: 19
- source bytes for retained downloads: 6,282,603
- rejected at download: `bcsstk01`, `bcsstk03`, and `bcsstk22` below the 1,000 stored-entry floor
- skipped at build as duplicate decompressed payloads: `bcsstk07` duplicate of `bcsstk06`; `bcsstk12` duplicate of `bcsstk11`

## Output

- natural sample boundary: one sparse-matrix attribute array for one source matrix
- geometry: sparse coordinate-matrix attributes over stored entries
- symmetry policy: preserve stored Matrix Market entries; do not expand symmetric matrices
- primary series: `row_index_u32`, `col_index_u32`, `entry_value_f64`
- primary samples: 57
- primary values: 2,300,385
- primary bytes: 12,268,720
- primary value count distribution: 1,288 / 1,874 / 3,987.5 / 15,100 / 51,912.5 / 94,915 / 219,812 min/p10/p25/median/p75/p90/max
- primary byte distribution: 5,152 / 8,330.4 / 16,560 / 71,428 / 261,040 / 611,975.2 / 1,758,496 min/p10/p25/median/p75/p90/max
- same-size fraction: 0.035088

Entry values alone are also above the collection floor: 19 samples, 766,795
float64 values, 6,134,360 bytes, and 15,100 median values per sample. Row and
column arrays are nevertheless marked primary because they are native Matrix
Market sparse-coordinate source fields, not generated helper coordinates.

## Series

| series | samples | values | bytes | value count min/median/max |
|---|---:|---:|---:|---:|
| `row_index_u32` | 19 | 766795 | 3067180 | 1288 / 15100 / 219812 |
| `col_index_u32` | 19 | 766795 | 3067180 | 1288 / 15100 / 219812 |
| `entry_value_f64` | 19 | 766795 | 6134360 | 1288 / 15100 / 219812 |

## Matrix Inventory

| matrix | rows | cols | stored entries | source bytes |
|---|---:|---:|---:|---:|
| `bcsstk02.mtx.gz` | 66 | 66 | 2211 | 14066 |
| `bcsstk04.mtx.gz` | 132 | 132 | 1890 | 9863 |
| `bcsstk05.mtx.gz` | 153 | 153 | 1288 | 6708 |
| `bcsstk06.mtx.gz` | 420 | 420 | 4140 | 27307 |
| `bcsstk08.mtx.gz` | 1074 | 1074 | 7017 | 44011 |
| `bcsstk09.mtx.gz` | 1083 | 1083 | 9760 | 39080 |
| `bcsstk10.mtx.gz` | 1086 | 1086 | 11578 | 67856 |
| `bcsstk11.mtx.gz` | 1473 | 1473 | 17857 | 102023 |
| `bcsstk13.mtx.gz` | 2003 | 2003 | 42943 | 338034 |
| `bcsstk14.mtx.gz` | 1806 | 1806 | 32630 | 299854 |
| `bcsstk15.mtx.gz` | 3948 | 3948 | 60882 | 373272 |
| `bcsstk16.mtx.gz` | 4884 | 4884 | 147631 | 880309 |
| `bcsstk17.mtx.gz` | 10974 | 10974 | 219812 | 2020150 |
| `bcsstk18.mtx.gz` | 11948 | 11948 | 80519 | 746903 |
| `bcsstk19.mtx.gz` | 817 | 817 | 3835 | 29225 |
| `bcsstk20.mtx.gz` | 485 | 485 | 1810 | 15843 |
| `bcsstk21.mtx.gz` | 3600 | 3600 | 15100 | 67372 |
| `bcsstk23.mtx.gz` | 3134 | 3134 | 24156 | 213119 |
| `bcsstk24.mtx.gz` | 3562 | 3562 | 81736 | 858278 |

## Novelty

This is not another dense table, raster, waveform, tensor, market event stream,
or time-frequency grid. The source representation is sparse coordinate format:
matrix structure is encoded by stored row and column fields plus values over a
large implicit matrix domain.
