# COSMIC-1 GNSS Radio-Occultation Calibrated L1 Excess Phase (JPL L1b v2.6) Float64

Native IEEE-754 float64 **calibrated GPS L1 excess phase** (metres, 50 Hz) of
individual COSMIC-1 radio-occultation soundings, as processed by NASA JPL
(institution_version v2.6) and hosted in the AWS Open Data "Earth Radio
Occultation" archive (`s3://gnss-ro-data`, format version 2.0). One sample is
one occultation: the L1 row of the NetCDF4 variable `excess_phase`, trimmed
of leading/trailing fill.

## Source and license

- Bucket: `https://gnss-ro-data.s3.amazonaws.com/contributed/v2.0/gnssro_cosmic1_jpl_l1b/YYYY/MM/DD/`
  (anonymous, not requester-pays). Files are named
  `gnssro_cosmic1_jpl_l1b_v2.6_cosmic1c<1-6>-G<PRN>-<YYYYMMDDHHMM>.nc4`.
- License: **CC BY 4.0** for JPL-contributed data. Evidence:
  - AWS registry entry (`awslabs/open-data-registry/datasets/gnss-ro-opendata.yaml`):
    "a creative commons license (https://creativecommmons.org/licenses/by/4.0/legalcode)
    applied to the data contributed by the NASA JPL of the California Institute
    of Technology ... the license in the attribute 'data_use_license'".
  - `gnss-ro/aws-opendata` Readme, "Data use licenses": NASA JPL, "a creative
    commons license" linking the same CC BY 4.0 legal code (both documents misspell
    the host as `creativecommmons.org`).
  - Every file's global attribute `data_use_license = "http://creativecommons.org/licenses/by/4.0/"`,
    enforced per file by download, build and verify.
  UCAR (COSMIC DAAC) and ROM SAF contributions carry other terms and are not used.
- Writer definition: `reformatting_system/rorefcat/src/rorefcat/Versions/version2.py`
  creates `excess_phase` as `f8 (signal, time)`, units `meter`,
  `_FillValue = -9.99e20`, with no compression.

## Selection (pinned in `sources.tsv`)

`discover.sh` (metadata listings only, run once at authoring time on 2026-10-06)
chose, for each month 2007-01 to 2016-12, the available day nearest the 15th
(the 15th everywhere except 2016-07-03, 2016-08-28, 2016-11-02, 2016-12-30,
when COSMIC-1 coverage was sparse), listed that day completely (continuation
tokens), sorted the keys and took 20 evenly spaced keys (`floor((2i+1)n/40)`).
Because keys sort by receiver, then GPS PRN, then time, the picks span all
six COSMIC-1 receivers and many transmitters. 2016-08-28 has only 13 files,
so the list has **2,393 files, 1,702,213,576 bytes**. Each row pins the S3 size
and single-part MD5 ETag; the list's SHA-256 is enforced by `scripts/gnssro.py`.

## Scripts

- `download.sh`: fetches the license README (checks the JPL CC BY 4.0
  sentence), performs a one-byte liveness GET, then downloads the 2,393 files in
  resumable parallel curl passes (`.part` files, `--continue-at -`,
  stall-based `--speed-limit`). Each file must match its pinned size and MD5.
  Then every file is decoded and its product identity checked
  (`check-downloads`); a wrong identity aborts.
- `build.sh`: runs the synthetic self-test, then for each file (in
  `sources.tsv` order) checks size and MD5, parses the HDF5 with
  `scripts/h5lite.py` (pure stdlib; every metadata checksum verified), checks
  the global attributes `mission=cosmic1`, `institution=jpl`,
  `institution_version=v2.6`, `VersionID=2.0`, `ShortName`, `ProcessingLevel=1B`,
  `data_use_license`, `GranuleID` (fatal if wrong), and checks that `excess_phase` is the exact
  little-endian IEEE f8 datatype, contiguous, unfiltered, with units `meter` and
  `_FillValue -9.99e20`. It then selects the unique row whose `phase_observation_code`
  starts with `L1` and whose `carrier_frequency` is 1575.42 MHz (row 0 is not
  assumed), applies the missing-value policy, and writes the raw bytes.
- `verify.sh`: runs the self-test, re-derives every sample independently
  (creation-order link index instead of the name index, separate `array`-based
  row/fill/50 Hz logic) and byte-compares. It re-reads each sample to reject
  fill, NaN/inf, |x| >= 1e9, fewer than 1,000 values, constant series, series
  with under 50% distinct values, and exact duplicates. It also checks the index
  fields, the recomputed drop counts and aggregate SHA-256, that all ten years
  are present, and the manifest `sample_count`/`total_size_bytes`.

## Missing-value policy

`_FillValue` (-9.99e20) and non-finite values are missing. Leading and trailing
missing values of the L1 row are stripped. A sounding with missing values inside the
remaining span is **dropped** (never gap-concatenated), as are soundings with
fewer than 1,000 valid values, a constant span, no unique L1 row at
1575.42 MHz, a non-50 Hz time axis, or a non-contiguous/filtered/non-f8
`excess_phase`. Drops are counted by reason in
`filtered/<id>/ingest_stats.json`. In the realized build **no sounding was
dropped and no L1 row needed trimming**: in all 2,393 files the L1 row is row 0,
code `L1W`, fully valid, at 50 Hz (fill occurs only in the excluded L2 rows).
The policy is kept as a guard but did not change any output.

## Output

- `samples/jpl_gnssro_cosmic1_l1b_excess_phase_f64/cosmic1_jpl_l1b_l1_excess_phase_f64/<year>/<GranuleID>_L1.f64le.bin`:
  raw little-endian float64, time order, one file per occultation
  (about 3,500-7,200 values in the probes, about 5,600 on average).
- `index/jpl_gnssro_cosmic1_l1b_excess_phase_f64/samples.jsonl`: one row per sample with the
  required fields plus source key, MD5, receiver, transmitter, occultation start,
  L1 code/row, span, time step, min/max (from stored float64 values) and SHA-256.
- Realized scope (build 2026-10-06): **2,393 samples, 13,471,361 float64 values,
  107,770,888 bytes**. Sample length is 1,799-10,850 values (median 5,550), duration
  36-217 s. That is 240 samples per year for 2007-2015 and 233 for 2016. Receivers
  c1/c2/c3/c4/c5/c6 contribute 620/347/105/398/468/455 samples. Aggregate SHA-256 is
  `1e6708153562e527f675c8b6de5d6b1451562d64a0f8237f1a2b65fa8cdc53d0`.
- Download: 1,702,213,576 bytes of whole files (MD5-verifiable against the S3
  ETag), so about 6.3% of downloaded bytes become primary. Byte-range projection of
  only the L1 extent would be about 6x leaner, but it would lose whole-object
  integrity checking.
- Value character: per-sample ranges span roughly -6,000 m to +26,900 m. Excess
  phase carries an arbitrary carrier-phase offset, so the absolute level differs
  between soundings. Most profiles are smooth ramps (about 2/3 increasing, 1/3
  decreasing in time). 7 of 2,393 samples contain short episodes of very fast change
  (tens of consecutive 20 ms steps of 50-90 m, swings of up to about 20 km), most likely
  open-loop tracking anomalies. These are native values and are kept unaltered.

## Homogeneity and novelty

One mission (COSMIC-1, receivers cosmic1c1-c6), one processing center and
version (JPL v2.6), one archive format (v2.0), one signal (GPS L1, 1575.42
MHz; code `L1W` in all probes), one unit (m), one sampling regime (50 Hz
open-loop). Nearest local material is `noaa_cors_rinex_observations_f64`
(ground-station RINEX carrier phase in cycles). RO excess phase is a different
quantity: a spaceborne limb-sounding atmospheric phase delay in metres, after
calibration.

## Notes

- The integer calendar attributes (`minute` is always 0 upstream) and the
  file-name stamp (start time rounded to the minute) are not cross-checked.
  `RangeBeginningDate/Time` is recorded as `occultation_start`.
- To regenerate the selection: `DISCOVERY_DIR=/tmp/x bash discover.sh`, then
  update `SOURCES_SHA256`, `EXPECTED_SOURCES` and `EXPECTED_SOURCE_BYTES` in
  `scripts/gnssro.py` if upstream changed.
