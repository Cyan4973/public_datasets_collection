# Crowd-Sourced Fitbit Intraday Heart Rate (Zenodo 53894) UInt8

Wrist optical heart-rate readings (integer beats per minute) from the
Furberg et al. crowd-sourced Fitbit exports, published on Zenodo under
CC BY 4.0 (DOI 10.5281/zenodo.53894). Thirty consenting Amazon Mechanical Turk
respondents submitted Fitabase exports for two consecutive periods,
2016-03-12 to 2016-04-11 and 2016-04-12 to 2016-05-12. Only some participants
have heart-rate data: the first export has 14 heart-rate Ids, and one of them
has only 439 readings.

## What is collected

- Source: `heartrate_seconds_merged.csv` (`Id,Time,Value`) inside each of the
  two zips. No other member is read. Steps, calories, METs, intensities, sleep
  and weight are out of scope.
- Primary series `fitbit_heartrate_bpm_u8`: the `Value` column (bpm), stored
  unchanged as uint8. There is one sample per (participant, export period),
  with the rows sorted by parsed timestamp.
- Sample files are named
  `samples/<id>/fitbit_heartrate_bpm_u8/<export>_pNN.bin`. `pNN` ranks the
  numeric Id over the union of heart-rate Ids in both exports, so the same
  participant gets the same ordinal in both periods. Ids are never emitted.

## Rules

- The two exports are never merged, even for the same participant.
- Each export keeps only rows whose local date falls inside its nominal
  window (2016-03-12..2016-04-11 and 2016-04-12..2016-05-12). Export 1
  spills 23,424 rows onto 2016-04-12. All of them are exact
  (Id, Time, Value) copies of export-2 rows, so they are dropped from
  export 1 rather than emitted twice. Export 2 has no out-of-window rows.
- Exact duplicate rows are removed. Rows that share an (Id, timestamp) but
  have different values are kept in source order and counted in the index
  field `same_timestamp_conflicts`.
- Timestamps (`M/D/YYYY h:mm:ss AM/PM`, naive local time) are parsed. Each
  Id's rows are stably sorted by (time, source row order).
- Values must be in 1..255. There is no fill value, and any violation fails
  the build.
- (Id, export) series with fewer than 1,000 readings are dropped.

## Caveats

- **Short effective span in export 1.** Although export 1 nominally covers
  2016-03-12..2016-04-11, nearly all of its heart-rate rows start on
  2016-04-01 (two participants start on 3/29 and 3/30). Export-1 samples
  therefore span about 11 days, and export-2 samples up to 31 days.

- **Irregular sampling.** Fitbit reports heart rate about every 5 s
  (sometimes 1 to 15 s) while worn and synced, and leaves longer gaps
  otherwise. The samples are value sequences only. Gaps are not encoded or
  filled; the index records the median gap per sample for reference.
- Participants used different Fitbit models (per the record description).
  The quantity, unit and integer lattice are the same for all of them.
- Heart rate is health-related personal data, though consented and
  pseudonymous. The manifest flags it conservatively.

## Scripts

- `download.sh`: curl both zips (45.7 MB total) and check the pinned size and
  MD5. It then checks that each heart-rate member has its pinned size and
  CRC32 and that every row parses.
- `build.sh`: writes the samples, `index/<id>/samples.jsonl`, and
  `filtered/<id>/ingest_stats.json` (row counts, duplicates, dropped Ids).
- `verify.sh`: re-derives every sample with a separate parser (regex
  timestamps, dict dedupe) and compares the bytes. It also checks the index
  fields, the hashes, the manifest totals, a 1,000-value minimum, at least
  10 distinct values per sample, and that no payload is duplicated.
