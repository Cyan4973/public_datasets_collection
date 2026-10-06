# MRO spacecraft-bus reconstructed attitude (NAIF CK type 3), float64

This recipe collects the reconstructed attitude of the Mars Reconnaissance
Orbiter (MRO) spacecraft bus, as archived by NASA/JPL NAIF in C-kernels. It
emits two homogeneous primary float64 series, one sample per whole CK type-3
segment:

| series | role | per sample | content |
|---|---|---|---|
| `mro_sc_bus_quaternion_f64` | primary | N x 4 | SPICE quaternion (q0 scalar first), rotation `MRO_MME_OF_DATE` -> `MRO_SPACECRAFT` (-74000) |
| `mro_sc_bus_angular_rate_f64` | primary | N x 3 | angular velocity, rad/s, given with respect to the base frame `MRO_MME_OF_DATE` |
| `mro_sc_bus_sclk_epoch_ticks_f64` | auxiliary | N | encoded SCLK time tags (1/256 s ticks), for alignment only |

Every pinned segment has N = 100,000 pointing records, about 4.3 h of ACS
telemetry at 5 or 10 Hz. The words are copied bit-exactly from the kernel: a
big-endian to little-endian byte swap, with no renormalisation, re-signing or
rounding.

## Source and rights

- Archival home: the NASA PDS MRO SPICE data set `MRO-M-SPICE-6-V1.0`,
  volume `MROSP_1000`, served by NAIF at
  `https://naif.jpl.nasa.gov/pub/naif/pds/data/mro-m-spice-6-v1.0/mrosp_1000/data/ck/`.
  The NAIF MRO CK `aareadme.txt` says the weekly reconstructed files "are
  automatically created by NAIF from the spacecraft engineering telemetry
  (orientation quaternions, spacecraft angular rates and solar array and
  antenna gimbal angles) ... These files are intended for OPS use and for
  archiving in PDS."
- Rights: NASA/JPL mission data in the NASA Planetary Data System, the same
  basis recorded for the accepted `nasa_naif_de440s_spk_coefficients_f64`
  recipe (`LicenseRef-US-Government-Public-Domain`). The explicit grant is
  NAIF's rules page (https://naif.jpl.nasa.gov/naif/rules.html): "SPICE
  kernels placed on the NAIF server may be downloaded and used by anyone",
  "Redistribution of SPICE kernels distributed by NAIF is permitted as long as
  they have not been modified", and commercial use needs "No fees or
  licensing". The emitted arrays are extracts made by this recipe, not NAIF
  products. JPL is Caltech-operated, so "public domain" is the corpus label;
  the NAIF rules are the operative permission.
- Fallback mirror: the USGS Astrogeology bucket `asc-isisdata`
  (`usgs_data/mro/kernels/ck/`) is an anonymous mirror of NAIF's operational
  kernel server and has no license object of its own. Its object sizes equal
  NAIF's `pub/naif/MRO/kernels/ck/` copies. The PDS copies are 1,024 or 2,048
  bytes longer because they embed a PDS label in the comment area. Probes
  showed byte-identical segment arrays on both hosts at addresses shifted by
  128 or 256 words. `download.sh` uses the mirror only if the PDS host fails
  a one-byte liveness check; both address sets are pinned in `sources.tsv`.

## Selection (bounded subset; `scripts/discover.py` -> `sources.tsv`)

1. In the PDS `data/ck` listing, keep names matching
   `^mro_sc_psp_YYMMDD_yymmdd(_vN)?.bc$`: weekly telemetry-based
   bus CKs. Predicted `...p.bc` files never match.
2. Per week, keep the highest archived version. Only 2015 is affected: PDS
   errata item 6 says the Sep 2014-Mar 2015 CKs were re-generated as `_v2`
   because the encoded-SCLK tags were 75 ms off, and PDS archives only
   `mro_sc_psp_150106_150112_v2.bc` for that week. Quaternion and rate values
   come from the same telemetry; only the time tags differ.
3. Keep the first week of each calendar year 2007-2017: 11 kernels.
4. From each kernel, take segment ordinals `floor(i*M/4)`, i = 0..3, over its M
   segments (33-40). That spreads four whole segments across the week. Each
   segment is the kernel's own DAF array: MSOPCK writes up to 100,000 records
   per segment.

Why stop at 2017: MRO moved routine attitude determination to
star-tracker-only "all-stellar" mode in 2018 to save its IMU. After that the
stored rate channel is no longer gyro-based, and it is roughly 6-100x
smoother:

| period | evidence | median abs. step of a rate component between records (rad/s) |
|---|---|---|
| 2007-2017 (IMU gyro) | realized: all 44 selected segments, all 100,000 records, each axis | 7.9e-6 to 1.2e-5 |
| 2007 - Jan 2018 (IMU gyro) | probe: first 1,000 records of the 44 selected segments and of 2017/Jan-2018 segment 0 | 6.5e-6 to 1.3e-4 |
| Jun 2018 - 2025 (all-stellar) | probe: first 1,000 records of segment 0 in 5 kernels (2018-06, 2018-10, 2019-01, 2022-01, 2025-01), av1 | 9e-8 to 1.3e-6 |

Mixing the two would bundle two generation processes, so the recipe keeps
only the gyro era: the selection is by date, before 2018. As a safety net,
`build.sh` and `verify.sh` also reject any segment whose noisiest-axis median
rate step is below 2e-6 rad/s. That threshold lies between the all-stellar
probe maximum (1.3e-6, Jan 2019) and the realized gyro minimum (7.9e-6). The
all-stellar evidence is probe-level, from 5 kernels.

Whole kernels are 208-256 MB each. Only the pinned segments are fetched:
44 x 801,002 words = 281,952,704 bytes, plus 59,209 bytes of DAF records,
HTTP headers and PDS labels.

## Decode and validation

`scripts/ck_type3.py` is a pure-stdlib DAF/CK reader written for this recipe.
It does not reuse the DE440s recipe code. `scripts/selftest.py` checks it on
synthetic segments of several (N, NINTS) shapes, including directory edge
cases and malformed inputs, and `build.sh` runs that test first.

- Per kernel: DAF file record (`DAF/CK  `, `BIG-IEEE`, ND = 2, NI = 6, FTP
  string, internal name `MRO TLM-Based SC Bus CK File by NAIF/JPL`), object
  size from the HTTP `Content-Range`, the full FWARD/NEXT summary chain ending
  at BWARD, segment count, and every descriptor equal to instrument -74000,
  frame -74900 (`MRO_MME_OF_DATE`), type 3, angular-velocity flag 1. The
  pinned descriptors (word addresses, SCLK coverage) must match exactly. PDS
  labels are pinned by SHA-256 and checked for `DATA_SET_ID`,
  `NAIF_INSTRUMENT_ID = -74000`, `PRODUCT_ID` and
  `PRODUCT_VERSION_TYPE = ACTUAL`.
- Per segment: length = 7N + N + floor((N-1)/100) + NINTS +
  floor((NINTS-1)/100) + 2, using the (NINTS, N) trailer; epochs strictly
  increasing and inside the descriptor coverage; SCLK directory entries equal
  epochs 100, 200, ...; interval starts are increasing epochs, the first being
  epoch 1; all values finite; |q| within 1e-6 of 1; the gyro-era rate guard.
- `download.sh` fetches each segment as one exact byte range into a `.part`
  file. It resumes by requesting only the missing tail. `curl -C -` is not
  used because combined with `-r` it drops the range. Only 206 responses with
  the expected `Content-Range` offset are accepted, stalls are handled with
  `--speed-limit/--speed-time`, and the size and structure are checked before
  the rename. All 44 segment SHA-256 values are pinned in `sources.tsv`
  (`segment_sha256`) and checked by download, build and verify. Two (2010
  segment 0, 2015 segment 0) were measured during authoring, when the PDS
  and mirror copies gave identical full-segment hashes. They matched the
  first realized download, which supplied the other 42.
- `verify.sh` re-decodes every raw segment with its own struct-based reader
  and checks byte equality of all samples. It also checks index fields,
  min/max computed from the stored doubles, non-constant samples and
  components, no duplicate quaternion samples, no stray files, the floors and
  the 1 GB cap, and that the manifest counts equal the realized output.

## Realized scope (first local run, 2026-10-05)

The download fetched 282,023,537 bytes, all from the PDS host; the mirror
fallback was not needed. It produced 44 segments from 11 kernels (2007-2017,
4 per kernel), every one with N = 100,000 and NINTS = 1, spanning 4.0-5.5 h
each (median 4.4 h). That gives 88 primary samples:

- quaternions: 44 x 400,000 values = 140,800,000 bytes
- angular rates: 44 x 300,000 values = 105,600,000 bytes
- primary total 30,800,000 values, 246,400,000 bytes, median 350,000 values
- auxiliary SCLK tags: 44 x 100,000 values = 35,200,000 bytes

`build.sh` (with the self-test), `verify.sh` (independent byte-exact
re-decode of all 44 segments) and `tools/autocollect/gate.py` passed, the
gate with no warnings. Ranges: quaternion components -0.99975 to 0.99974,
rate components -1.654e-3 to 1.655e-3 rad/s. Max |q|-1 per segment is
7.2e-9 to 9.6e-9. There are no quaternion hemisphere (q -> -q) flips.
General-purpose compressors on three spot-checked samples: quaternions zlib-9
0.92 / xz 0.55-0.57; rates zlib-9 0.92-0.95 / xz 0.85-0.86.

## Character and caveats

- Quaternion components are telemetry decimals with 8 fractional digits: in
  all 44 segments, 100% of the 17.6 M components equal their 8-decimal
  rounding. Their low mantissa bits are therefore decimal-structured, which
  is part of why xz reaches about 0.55. They are not float32-representable,
  so float64 is the honest width.
- Rates carry full double precision, because NAIF's MSOPCK received IMU
  body-frame rates (`ANGULAR_RATE_FRAME = 'INSTRUMENT'`) and the CK stores the
  vector with respect to the base frame. The CK comments warn that the IMU
  rates are shifted forward in time by a small unknown offset relative to the
  quaternions.
- Attitude is mostly nadir-tracking, so it is smooth and orbit-periodic
  (|w| ~ 9.4e-4 rad/s, the orbital rate). Whole-segment rate-step medians are
  uniform (7.9e-6 to 1.2e-5), but there are local stretches of much larger
  steps: the first 1,000 records of 2012 segment 10 and 2015 segment 0 reach
  4e-5 to 1.3e-4. These fit off-nadir slews or other ACS activity; the recipe
  does not identify the cause. Telemetry cadence switches between 5 and
  10 Hz within segments.
- The 100,000-record segment length is a NAIF writer convention, but it is the
  kernel's own array boundary, as with the SPK segments of the DE440s recipe.

## Novelty

New source and quantity: spacecraft attitude estimate and inertial rates of a
Mars orbiter. Nearest local families:
- `nasa_naif_de440s_spk_coefficients_f64`: same NAIF DAF container, but
  planetary-ephemeris Chebyshev coefficients from generic kernels.
- `tum_rgbd_groundtruth_pose_f64` (downstream `tum_rgbd_pose_f64`): one
  handheld-camera motion-capture quaternion sequence.
- `har_smartphone_uci` (downstream `har_body_gyro`): smartphone gyro windows.

No CK or spacecraft attitude material exists locally, in the registry, or
downstream.

## Run

```bash
bash staging/naif_mro_sc_bus_attitude_ck_f64/download.sh   # network; ~282 MB of ranges
bash staging/naif_mro_sc_bus_attitude_ck_f64/build.sh      # local only
bash staging/naif_mro_sc_bus_attitude_ck_f64/verify.sh
```

`discover.sh` reproduces the selection metadata (about 2.3 MB of listings and
records) and writes a fresh `sources.tsv` under
`$DATA_DIR/discovery/<id>/` for comparison. All scripts honour `DATA_DIR` and
log to `$DATA_DIR/logs/naif_mro_sc_bus_attitude_ck_f64/`.
