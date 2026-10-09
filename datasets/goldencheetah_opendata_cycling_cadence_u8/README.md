# GoldenCheetah OpenData Per-Second Cycling Cadence (uint8)

Pedalling cadence (crank rpm) recorded by cyclists' bike computers with crank
or pedal cadence sensors. Each sample is one complete cycling activity's `cad`
column, stored as native uint8. Only activities on a 1 s time lattice are kept.

- Source: GoldenCheetah OpenData Project, OSF `6hfpz`
  (<https://osf.io/6hfpz/>, DOI 10.17605/OSF.IO/6HFPZ)
- License: CC0 1.0 Universal (OSF node license
  `563c1cf88c5e4a3877f9e96c`); the upstream README says the data is fully
  anonymised.
- Series: `gc_bike_cadence_rpm_u8` (primary, `native_numeric`), one sample
  per kept activity.

## Source layout

The osfstorage root holds 6,613 athlete zips (`<uuid>.zip`, 115.6 GB). Each zip
contains:

- `{<uuid>}.json`, with a `RIDES` list holding one entry per activity: the UTC
  `date`, `sport`, a 15-character `data` presence-flag string (the 6th
  character is `C` when cadence was recorded) and metrics. It also has an
  `ATHLETE` block with gender and year of birth, which the recipe never reads.
- one CSV per activity, `YYYY_MM_DD_HH_MM_SS.csv`, named after the start time
  in the athlete's local clock, with header `secs,km,power,hr,cad,alt`.
  GoldenCheetah exports each activity at the recording device's own interval.
  Most are 1 s, but some are 0.5 s (2 Hz), some are smart-recording steps of
  1.26 s or 2-8 s, and some have doubled or repeated-timestamp rows.
  Recording pauses show up as jumps in `secs`.

## Selection

`sources.tsv` pins 460 zips (2,807,759,073 bytes) with OSF file id, size,
SHA-256 and MD5. The list comes from the name-sorted OSF files-API listing
made on 2026-10-09. The rule: walk zips in name order (random UUIDs), keep
those of 100 KB to 20 MB, and stop once 2.8e9 cumulative bytes are reached.
The 20 MB cap keeps prolific athletes (zips up to 264 MB) from dominating.
`discover.sh` re-lists the project and re-derives the selection.
Unsorted offset paging of the OSF API drifts (duplicates and misses), so the
listing always uses `sort=name`.

## Conversion

1. Match each CSV to its RIDES entry. The local-minus-UTC offset must be a
   whole quarter hour within ±14 h. If several entries qualify, the athlete's
   modal offset among unique matches decides. CSVs that are still ambiguous,
   or that claim the same entry, are skipped. (Upstream's own
   `opendata-python` matches on minute:second loosely.)
2. Keep `sport == "Bike"` entries whose 6th flag character is `C`. Run cadence
   is in steps/min and can exceed 255; VirtualRide and free-text sport labels
   are excluded.
3. Read the `cad` column of every row as a base-10 unsigned integer and write
   the values as raw uint8 in row order.
4. Time lattice: keep only activities whose `secs` column is an integer on
   every row, strictly increasing (every step at least 1), with at least 95%
   of steps exactly 1 s. Remaining steps over 1 s are recording pauses and are
   kept as published. Nothing is resampled.
5. Same-athlete overlap rule: per athlete, order the activities that pass
   every per-activity filter by RIDES UTC start (ties by CSV name). Keep one
   only if its start is at or after the latest end (UTC start + last `secs`)
   among the athlete's already-kept activities. Otherwise skip it as
   `overlapping_recording`; these are mostly dual-device recordings of one
   ride. The global byte-identical dedup then runs in emitted order: athletes
   in `sources.tsv` order, chronological within an athlete.

Skip policy. Whole activities are dropped and no cell is rounded or imputed.
An activity is skipped if it has:

- any empty, non-integer (GoldenCheetah interpolated values such as `82.5`)
  or >255 cad cell, or any malformed row;
- `secs` off the 1 s lattice (`secs_not_integer`,
  `secs_not_strictly_increasing`, `secs_step_not_1s`), checked before the
  degeneracy rules;
- fewer than 1,000 values;
- more than 90% zeros;
- fewer than 10 distinct values;
- any nonzero value repeated for 300 or more consecutive rows (a held-value
  dropout plateau);
- an overlap with an earlier kept recording of the same athlete;
- a payload byte-identical to one already emitted.

One athlete zip, `1293c64a-7388-4366-9a8c-3c7951ae61a8.zip`, is skipped whole.
Its published RIDES JSON is not valid JSON (a missing `,` at line 18570) even
though the file matches the OSF SHA-256, so no activity can be matched to its
sport. It is pinned in `KNOWN_BAD_RIDES_JSON`. Any other JSON failure is fatal,
and so is a listed zip that turns out to parse.

Skip counts per reason and per athlete go to
`filtered/<id>/ingest_stats.json`. Realized counts for the current build
(70,263 CSV members):

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
| athlete zip with malformed RIDES JSON | 1 zip |

Kept: 19,108 activities, 94,052,531 values (median 3,893) from 377 athletes.
The index also carries the auxiliary fields `secs_last` and `secs_gap_count`
(steps over 1 s) for traceability; they are not series.

## Scripts

- `download.sh`: resumable curl (`-C -`, stall detection, no max-time) via
  `https://osf.io/download/<id>/`, which redirects to signed URLs that expire.
  It checks size, SHA-256 and MD5, then runs `gc_cadence.py check-download`
  (zip CRCs, RIDES JSON, member names and CSV headers).
- `build.sh`: `gc_cadence.py build` writes the samples, `samples.jsonl` and
  ingest stats.
- `verify.sh`: `gc_cadence.py verify` re-derives every sample with a separate
  implementation (datetime O(n·m) matching, the `csv` module,
  `itertools.groupby` plateau detection). It compares bytes, index fields and
  manifest totals, and checks the floors.

## Sizing history

Author-phase probe: seven athlete zips (21 MB) held 393 Bike+C activities.
78 of them contained fractional cadence, and 315 were clean integer series
(about 17 download bytes per kept byte).

First build, on a 263-zip / 1.6e9-byte selection: 12,030 activities and
58.5 MB kept. Fractional-cadence drops were much more common than in the
probe (8,717 activities). In a sample of affected CSVs, half had under 1%
fractional cells, but a quarter had 35% or more (heavy interpolation). The
policy stayed strict: whole activities are dropped and nothing is rounded.
The selection target was raised to 2.8e9 bytes with the same rule, so the
first 263 rows are unchanged and only more athletes are added. That aims
for about 100 MB kept.

Repair 1 (judge): the build added the 1 s time-lattice filter and the
same-athlete overlap rule. That reduced the output from 20,722 activities
(102.7 M values) to 19,108 activities (94.1 M values). The selection and
downloads are unchanged.
