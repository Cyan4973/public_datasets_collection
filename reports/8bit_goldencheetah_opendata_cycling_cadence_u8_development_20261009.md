# GoldenCheetah OpenData cycling cadence uint8 development

## Outcome

Accepted `goldencheetah_opendata_cycling_cadence_u8` after one judge repair. Each sample is the complete pedalling-cadence (`cad`, crank rpm) column of one cycling activity from the CC0 GoldenCheetah OpenData project, stored as native uint8.

It is the first exercise-cadence family in the local or downstream corpus, and the quantity and source are both new (novelty kind: `new_quantity`). The nearest existing material by bytes is the downstream AEGIS OBD PID u8 family. zlsim distance is 0.0695 with compression loss 0.090, and the verdict is OK.

Repair 1 made two changes:
- a strict 1 s time-lattice filter, which removed 0.5 s, smart-recording, doubled-row and repeated-timestamp exports;
- a same-athlete overlap rule, which removed dual-device recordings of one ride.

Sources and downloads were unchanged.

## Source and rights

- Source: Open Science Framework project `6hfpz`, "GoldenCheetah OpenData Project" (DOI 10.17605/OSF.IO/6HFPZ).
  - The osfstorage root holds 6,613 athlete zips (`<uuid>.zip`, 115.6 GB total).
  - Files are fetched through `https://osf.io/download/<file id>/`, because the signed redirects expire.
- Selection: 460 zips (2,807,759,073 bytes), pinned in `sources.tsv` with OSF id, size, SHA-256 and MD5.
  - Rule: walk zips in ascending UUID-name order, keep those of 100 KB to 20 MB, and stop at 2.8e9 cumulative bytes.
  - The 20 MB cap stops prolific athletes from dominating. `discover.sh` re-derives the selection from a name-sorted files-API listing.
- License: CC0 1.0 Universal.
  - The OSF node `6hfpz` license relationship points to `563c1cf88c5e4a3877f9e96c`, which the OSF licenses API names "CC0 1.0 Universal".
  - The zips are the node's own osfstorage files, so the license covers the exact data objects.
- Privacy: the upstream README says "The data is entirely anonymised, no personally identifiable information is stored or made available."
  - Athletes appear only as random UUIDs, and the CSVs carry no GPS.
  - The ATHLETE demographics block is never emitted.

## Shape and conversion

- Natural record: one activity CSV (`YYYY_MM_DD_HH_MM_SS.csv`, header `secs,km,power,hr,cad,alt`) inside an athlete zip.
- Metadata matching: each CSV is matched to its `RIDES` JSON entry by local-to-UTC offset. The offset must be a whole quarter hour within ±14 h, with the athlete's modal offset breaking ties. Ambiguous CSVs are skipped (111).
- Activities kept:
  - `sport == "Bike"` with `C` as the 6th character of the `data` flags. Run cadence is in steps/min and is excluded, as are VirtualRide and free-text sports.
  - every `cad` cell a base-10 integer in 0..255, with no rounding or imputation;
  - an integer, strictly increasing `secs` column with at least 95% of steps exactly 1 s.
- Degeneracy rules: an activity is dropped if it has fewer than 1,000 values, more than 90% zeros, fewer than 10 distinct values, or a nonzero plateau of at least 300 rows.
- Overlap and dedup: per athlete, an activity is kept only if its UTC start is at or after the latest end of the athlete's already-kept activities. A global byte-identical dedup follows.
- Conversion: the `cad` column is copied exactly into raw uint8 in row order. FIT stores cadence natively as uint8 rpm, so the width is honest. Pauses longer than 1 s are kept as published.
- Auxiliary index fields: `secs_last` and `secs_gap_count`. They are not series.

Skip counts (70,263 CSV members):

| reason | activities |
|---|---|
| not_bike | 20,909 |
| non_integer_cadence | 15,116 |
| no_cadence_flag | 11,370 |
| short_activity | 1,412 |
| secs_not_strictly_increasing | 940 |
| secs_not_integer | 443 |
| duplicate_payload | 376 |
| secs_step_not_1s | 189 |
| overlapping_recording | 161 |
| unmatched_ride | 111 |
| constant_plateau | 61 |
| mostly_zero | 39 |
| empty_cadence_cell | 12 |
| low_distinct | 12 |
| cadence_above_255 | 3 |
| bad_csv_name | 1 |

One zip, `1293c64a-…`, has syntactically invalid upstream RIDES JSON (its SHA-256 matches OSF), so the athlete is skipped whole.

## Accepted output

- Primary series: `gc_bike_cadence_rpm_u8` (uint8, little-endian, `native_numeric`)
- Primary samples: 19,108, from 377 athletes
- Primary values and bytes: 94,052,531
- Values per sample:

  | min | p10 | median | p90 | p99 | max |
  |---|---|---|---|---|---|
  | 1,000 | 1,806 | 3,893 | 8,993 | 17,386 | 69,131 |

- Athlete concentration: the top athlete holds 1.79% of values and the top 10 hold 15.6%. The largest athlete has 683 activities.
- Ride dates: 2014–2020, plus two activities with wrong device clocks (1989, 2009).
- Value distribution:

  | values | share |
  |---|---|
  | 0 (coasting) | 10.75% |
  | 60–79 rpm | 26.2% |
  | 80–99 rpm | 50.6% |
  | 100–119 rpm | 5.3% |
  | 200–253 | 1,458 values |
  | 254 | 104 values |
  | 255 | 0 |

- Aggregate SHA-256 over samples concatenated in sorted file-name order: `81f33c3b35787de40c564694f32c6e2823b2f61c584e181d1c1ff00793966e34`

## Judge checks

- Mechanics: `gate.py` passed with no warnings. The ingest_stats skip reasons plus the kept count reconcile exactly to the 70,263 CSV members.
- Reproducibility: I ran `verify.sh` myself and it reported `verify ok samples=19108 total_values=94052531 median_values=3893.0 athletes=377`.
  - Verify is a separate implementation (csv module, datetime matching and overlap frontier, `itertools`) and compares every sample byte for byte.
  - build and verify make no network calls and contain no credentials.
- Bytes:
  - 250 random samples, re-parsed with my own minimal parser, match the zip CSVs byte for byte. Each was confirmed as sport=Bike with flag `C` and at least 95% one-second steps.
  - From the index: no activity has `secs_last < n−1`, none has more than 5% non-1 s steps, no same-athlete overlaps remain, and no duplicate SHA-256s exist.
  - The histogram is physically plausible, and the FIT invalid value (255) is absent.
- Near-duplicates: I ran content-defined window scans plus a cross-athlete start-time scan (1,471 coincident pairs). Five near-duplicate pairs remain, 0.03% of samples:
  - 2 same-athlete re-dated copies;
  - 2 cross-athlete near-identical copies (`04462c2c`/`0b03c530`);
  - 1 cross-athlete dual-device pair.

  This is negligible, so no repair was requested.
- Rights: I fetched the OSF node and license API records and the upstream README myself.
- Novelty: `novelty.py` (URLs and terms) and the breadth-key queries match nothing comparable. The driver's zlsim measured OK.
- Residual notes:
  - The `gc_cadence.py` module docstring still mentions "1 s steps". This is cosmetic.
  - The extraction ratio is about 30:1, which is tolerable given the large absolute kept signal and the lack of a leaner source.
