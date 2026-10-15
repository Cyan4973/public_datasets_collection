# ECMWF IFS HRES open data 0p4-beta: 500 hPa relative vorticity, GRIB2 16-bit packed codes (uint16)

One sample per 00z ECMWF IFS HRES run between 2023-01-18 and 2023-06-27:
the complete global 500 hPa relative vorticity field at forecast step 24 h, as the
**stored GRIB2 simple-packing integer codes** (data representation template 5.0,
16 bits per value, no bitmap). Each field is 900 x 451 = 405,900 values on the
0.4 deg regular lat/lon grid, written as little-endian uint16 (811,800 bytes).

- Source: ECMWF real-time forecasts (open data), replicated to the AWS Open Data
  bucket `s3://ecmwf-forecasts` (eu-central-1). The recipe uses the CloudFront
  distribution listed for that bucket in the registry (`d2zvc0wgha4k2l.cloudfront.net`),
  falling back to the S3 endpoint. Both serve the same objects: SHA-256 is
  identical for the probed 20230118 index and message.
- License: CC-BY-4.0 plus the ECMWF Terms of Use. Evidence is the AWS Open Data
  Registry entry
  `https://raw.githubusercontent.com/awslabs/open-data-registry/main/datasets/ecmwf-forecasts.yaml`:
  "This ECMWF data is published under a Creative Commons Attribution 4.0 International
  license (CC-BY-4.0) and the ECMWF Terms of Use". The citation is
  https://doi.org/10.21957/open-data.

## What the numbers are

A GRIB2 template-5.0 field stores, per grid point, an unsigned integer code `X` such
that the physical value is `(R + X * 2^E) / 10^D`. R is a float32 reference value
(the field minimum), E is the binary scale factor and D is the decimal scale factor;
all three are set per message by ECMWF's encoder. In the realized 155 messages D = 0 and
E = -25 (129), -24 (23) or -26 (3). Every field has code_min 0 and code_max between
33,159 and 65,256, so both bytes carry information. Because E differs, the code lattice
spacing in physical units is not the same for all samples.
R, E and D vary per message. For this reason:

- the primary series is the codes, not reconstructed float values; this is the exact
  stored representation, not a local requantization;
- R, E, D, code min/max, physical min/max (s-1) and all hashes are written per sample
  into `index/<id>/samples.jsonl` and `filtered/<id>/packing_params.tsv` as auxiliary
  metadata, so physical values can be reconstructed exactly.

Scan order is GRIB scanning mode 0: rows from 90 N to 90 S, and within a row eastward
starting at 180 deg (La1 = 90, Lo1 = 180, La2 = -90, Lo2 = 179.6).

## Why this window

- The bucket starts at 20230118.
- IFS cycle 48r1 became operational with the 06 UTC run on 2023-06-27 (ECMWF
  "Implementation of IFS Cycle 48r1"). From then on, open data is CCSDS-packed
  (template 5.42), which needs a decoder that is not available in pure stdlib. The
  probe confirms this: the vo/500 24 h message is 811,996 bytes (simple packing) for
  20230627 00z and about 545 KB from 20230627 12z and 20230628 00z onward.
- The 2023-06-27 00z run is therefore the last one, and every sample comes from one
  model cycle (47r3) and one packing regime.
- One parameter, one level, one step and one run time per day. Sibling parameters
  and levels in the same files (d, vo at other levels, tp) are not collected.

The window has 161 calendar days; 155 are realized. 20230427..20230502 (6 days) have no
published 00z 0p4-beta 24 h `.index` (HTTP 404; the S3 list-type=2 listing for those date prefixes is empty, so the gap is in the source bucket). Days without a published file are skipped
and listed in `downloads/<id>/missing_days.tsv`, and `verify.sh` requires every day in
the window to be either present or listed there.

## Scripts

- `download.sh`: for each day, GET the ~18 KB `.index` (ECMWF JSON lines) of
  `<date>/00z/0p4-beta/oper/<date>000000-24h-oper-fc`, then pick the single
  `param=vo, levelist=500, step=24` line. That line must have `_length` 811996 and
  matching date, time, stream, type and levtype. The script then range-GETs exactly
  those bytes from the `.grib2`. S3 `SlowDown` 503s are retried with back-off,
  alternating between the CloudFront and S3 hosts. A range request must be answered
  206. The body must be exactly 811,996 bytes starting with `GRIB`, and must pass the
  full structural check in `scripts/grib2_vo500.py check`. Error XML bodies are
  discarded. If any day is still failing at the end, the script exits non-zero, and a
  re-run resumes because cached days are re-validated and skipped. The script writes
  `messages.tsv` with the offset, length, SHA-256 and canonical URL of each message.
  Realized download is 128.7 MB (155 messages plus index files).
- `build.sh`: `scripts/grib2_vo500.py build`, a pure-stdlib GRIB2 section walker. It
  asserts edition 2, centre 98, discipline 0, grid 3.0 900x451 at 0.4 deg, product
  4.0 with parameter 2/12 at 24 h on isobaric 50000 Pa, data 5.0 with 16 bits and
  405,900 points, and bitmap indicator 255. It byte-swaps section 7 to little-endian
  and writes `samples/<id>/vo500_packed_codes_u16/<yyyymmdd>.bin` plus the index.
- `verify.sh`: `scripts/verify_vo500.py`, an independent section walker that does not
  import the build parser. It re-derives each sample by byte-lane swapping section 7,
  then checks the R/E/D and statistics metadata, the window accounting, duplicates and
  the manifest totals. It rejects constant fields, fewer than 1,000 distinct codes, a
  single code covering more than 50% of a field, code_max < 256, and implausible
  physical ranges.

The parser was self-tested on two real messages (20230118 and 20230627), and mutated
copies were rejected: wrong bits, template 42, bitmap present, wrong parameter, level
or step, edition 1, bad magic, and truncation.

## Novelty

- No GRIB-derived recipe exists in `datasets/`, the registry or the downstream corpus
  (`novelty.py --url ecmwf-forecasts`: no matches).
- The nearest local family is `weatherbench2_era5_pressure_level_fields_f32`: ERA5
  reanalysis (also ECMWF), regridded float32 fields. This recipe differs in
  representation (16-bit packed integer codes), product (operational HRES forecast,
  not reanalysis), variable (vorticity, which is not among the WeatherBench2 fields)
  and grid.
- The byte-level similarity check (zlsim) runs after the build.
