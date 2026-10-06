# HamSCI PSWS Grape V1 Received WWV 10 MHz Carrier Frequency (float64)

Status: staging draft. download, build and verify have run, and the gate
passes. 903 samples, 74,966,875 float64 values, 599,735,000 bytes. Median
sample: 84,372 values (min 4,328, max 84,377). All 920 keep/exclude
statuses are pinned in `sources.tsv`.

## What is collected

The HamSCI Personal Space Weather Station (PSWS) network runs low-cost
**Grape V1** HF receivers, each referenced to a GPS-disciplined oscillator
(GPSDO). Each receiver tracks the carrier of a time-standard broadcast and
logs an estimate of its received frequency about once per second. The NIST
WWV carrier is stable to better than 1 part in 10^12, so the logged frequency
minus 10,000,000 Hz is mostly the Doppler shift that the moving ionosphere
imposes on the HF path. That shift is typically a few tenths of a hertz to a
few hertz. It changes at sunrise and sunset, and with travelling ionospheric
disturbances and solar flares.

Source: Zenodo record [6590283](https://doi.org/10.5281/zenodo.6590283),
"Grape V1 Data: Frequency Estimation and Amplitudes of North American Time
Standard Stations" (Kristina Collins, HamSCI, published 2022-05-26, CC BY 4.0).
The record holds 3,017 gzip CSV files, one per station, beacon and UTC day.
The data paper is Collins et al. (2023), *Earth Syst. Sci. Data* 15,
1403–1418, doi:10.5194/essd-15-1403-2023. Its Code and data availability
section cites this exact record DOI.

One sample is the complete `Freq` column of one station-day file
`<date>T<HHMMSS>Z_<node>_G1_<grid>_FRQ_WWV10.csv.gz`, in file row order,
decoded to little-endian float64. A full day has about 84,000 rows.

## Selection

All 920 record files from **Grape Gen 1 (`G1`) receivers decoding WWV
10 MHz** are selected. `sources.tsv` pins them with key, node, grid, file
start time, size, Zenodo md5 and expected status, ordered by node and then
start time.

| node | grid | station-days | kept | kept values | first | last |
|---|---|---|---|---|---|---|
| N00009 | FN20ge (Collegeville PA) | 294 | 292 | 24,110,796 | 2020-07-21 | 2021-05-15 |
| N0000007 | EN91fh (Macedonia OH) | 284 | 280 | 23,529,547 | 2020-07-28 | 2021-05-15 |
| N0000014 | FN21ei | 134 | 132 | 10,844,244 | 2021-01-01 | 2021-05-15 |
| N0000015 | FN20mp | 113 | 110 | 9,195,510 | 2021-01-23 | 2021-05-15 |
| N00010 | EN91ii | 73 | 72 | 6,062,109 | 2021-03-04 | 2021-05-15 |
| N0000029 | DM45dc (Flagstaff AZ) | 22 | 17 | 1,224,669 | 2021-04-09 | 2021-05-15 |

Excluded at selection:
- **Other beacons.** WWV5 (836 G1 files), WWV2p5 (308) and CHU7 (255) have
  different carrier frequencies, so their values sit on a different scale.
  Mixing scales would break homogeneity (the bookticker lesson).
- **S1 receivers.** Nodes N0000002, N0000008 and N0000013 are commercial
  receivers on an external reference (402 WWV10 files). They are a
  different instrument.
- **'Unknown' files** (3).

The full G1 WWV10 population is taken (614,396,212 download bytes, about
600 MB of primary output). This is under the 1 GB cap, so no subsetting
rule is needed.

## Whole-file rules (same in build and verify)

A station-day file is kept unless one of these pinned rules fires. The
reasons combine, as in `exclude:malformed_row+too_short`.

- `header_mismatch`: the `#,...` identity line or the `#` block does not
  match the file name's node and grid, receiver `G1` and beacon `WWV10`, or
  the `UTC,Freq,Vpk` header is missing.
- `reference_not_gpsdo`: `# Frequency Standard` does not name a GPSDO.
- `malformed_row`: a data row is not `YYYY-MM-DDTHH:MM:SSZ, <d+.ddd>,
  <token>`, for example a `nan` frequency. The exception is an unterminated
  final line, which is dropped and counted as `truncated_tail_dropped`.
- `time_order`: a row timestamp steps backward, or a row falls on another
  UTC date. Repeated seconds are allowed and counted as `steps_0s`.
- `out_of_band`: any value has |Freq − 10 MHz| > 100 Hz. That means a
  re-tuned receiver or a different carrier.
- `too_short`: fewer than 3,600 rows (one hour at the nominal cadence).
- `constant`: fewer than two distinct values.

### Realized exclusions (17 of 920)

| reason | files | what the data showed |
|---|---|---|
| `time_order` | 8 + 1 | Backward clock jumps of 685–2,783 s that land on `hh:17:15`-style times. This looks like a Raspberry Pi restoring a saved clock after a reboot until NTP resyncs, so a segment of rows carries wrong timestamps. The 2020-07-30 reboot file also has 3 rows at about 20,000,000 Hz (WWV 20 MHz) right after the jump. |
| `out_of_band` | 4 + 2 | N0000029 2021-04-13T211128Z and 2021-04-23T001758Z are labelled WWV10 but contain about 4,999,999.75 Hz, i.e. WWV 5 MHz. Three files have long runs at a constant offset: N0000007 2020-09-29 (+370 Hz, 4,069 values), N0000007 2020-11-17 (−684 Hz, 29,957 values) and N0000029 2021-04-09T045433Z (+402 Hz, 7,760 values). |
| `too_short` | 3 + 1 | 56, 1,759, 2,103 and 3,222 rows. |

No file was excluded for `header_mismatch`, `reference_not_gpsdo`,
`malformed_row` or `constant`. All 920 headers declare `LB GPSDO`, and every
row of every file parses. The rules were first written with a ±1 kHz band
and a "strictly increasing, not before the file start" time rule. The first
build showed that was too loose for the re-tuned runs. It was also too
strict for duplicated seconds (53 rows in 47 otherwise complete days) and
for files named `...000001Z` whose first row is stamped `00:00:00` (7
files). The final rules above came from that inspection and are pinned per
file.

### Gaps and fades

Gaps are explicit but not filled. Across the kept samples:
- 73,139,962 steps are 1 s.
- 1,808,480 are 2 s: the logger skips about 2.4% of seconds, so a full day
  has about 84.4k rows, not 86,400.
- 17,477 are longer gaps (outages and partial days).
- 53 are repeated seconds.

In total 2,408,216 seconds are missing. Kept rows are emitted as logged,
with no padding, NaN fill, interpolation or resampling. Each index row
records `first_row_utc`, `last_row_utc`, `span_seconds`, `missing_seconds`,
`steps_0s`/`1s`/`2s`/`gt2s` and `max_step_seconds`.

In-band excursions during beacon fades are real estimator output and are
kept. Kept values span 9,999,989.721 to 10,000,010.400 Hz.

Known caveat, node N00009 from 2021-01 onward:
- 993,480 values (1.3% of all kept values; 4.1% of N00009's) deviate by
  more than 5 Hz, and 99.995% of them come from N00009.
- The excursions are bounded within about −6..+10.4 Hz, consistent with the
  estimator's search window saturating when the signal is weak.
- N00009's daily median offset also shifts between days, ranging from −4.5
  to +7.9 Hz, with 89 days beyond ±0.2 Hz. That suggests calibration or
  configuration changes at the station as well as fades. By comparison,
  N0000014, N0000015, N0000029 and N00010 keep every daily median within
  ±0.2 Hz, and N0000007 has 5 days beyond it, down to −1.0 Hz.

These days are kept: they are the same instrument, unit, estimator and
1 mHz lattice, and dropping them would need a station-quality judgement the
source does not document. The index carries `values_beyond_5hz` and
`values_beyond_10hz` per sample, so downstream can filter.

## Conversion and width

`Freq` is printed as `%12.3f`, for example `  9999999.762` or
` 10000000.022`: 10–11 significant digits on a 1 mHz lattice. Near 1e7 the
float32 spacing is 1 Hz, which would erase the signal. `float(token)` gives
the nearest binary64, and `'%.3f' % value` reproduces the exact source token.
`verify.sh` checks that property for every value. Of the 74,966,875 kept
values, 74,672,873 (99.6%) are not float32-exact. The exact ones are only
whole-hertz values.

The `Vpk` amplitude column is a different quantity and is not emitted. The
header metadata (callsign, city, coordinates) is not emitted either.

## Source version note

The record's metadata says it `isObsoletedBy` 10.5281/zenodo.6622111. That
newer concept (latest record 13637199, CC BY 4.0) repackages the files
uncompressed into yearly ZIPs (2020.zip is 0.89 GB, 2021.zip is 3.15 GB)
and extends coverage to 2024. Two of this record's WWV10 files decompress to
the same size and CRC32 as the matching members of 13637199/2020.zip, so the
per-file record is content-identical for what it holds. It is also the DOI
the ESSD data paper cites, and it allows exact per-file md5-verified
downloads without range-extracting multi-GB ZIPs.

## Running

```
bash staging/hamsci_grape1_wwv10_doppler_frequency_f64/download.sh   # ~614 MB, 920 paced requests
bash staging/hamsci_grape1_wwv10_doppler_frequency_f64/build.sh
bash staging/hamsci_grape1_wwv10_doppler_frequency_f64/verify.sh
```

Each script honours `DATA_DIR` (default `.data`) and logs to
`$DATA_DIR/logs/hamsci_grape1_wwv10_doppler_frequency_f64/`. Download pacing
can be changed with `GRAPE_PACE_SECONDS`, which defaults to 1. A re-run skips
files whose size and md5 already match, and resumes `.part` files.

Other files:
- `discover.sh`: a metadata-only check that regenerates the selection from
  the live record API and diffs it against `sources.tsv`.
- `scripts/selftest.py`: runs the build parser and the independent verifier
  on 16 synthetic station-day files. They cover every rule, repeated
  seconds, backward clock steps, a 5 MHz file labelled WWV10, truncated
  tails, gaps, a corrupted sample and tampered gap bookkeeping. Run it from
  a scratch directory.

Outputs:
- `samples/<id>/grape1_wwv10_received_frequency_hz_f64/<node>/<stem>.f64`
- `index/<id>/samples.jsonl`
- `filtered/<id>/file_classification.tsv` (all 920 files, with statuses and
  statistics)
- `filtered/<id>/ingest_stats.json`
