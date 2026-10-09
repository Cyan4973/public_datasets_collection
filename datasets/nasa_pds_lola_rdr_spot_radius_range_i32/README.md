# LRO LOLA RDR per-spot lunar radius and laser range, mapping orbit (int32)

This recipe collects per-laser-spot measurements from the Lunar Orbiter Laser
Altimeter (LOLA) on NASA's Lunar Reconnaissance Orbiter. The source is the
Level-3 Reduced Data Record (PDS collection LRO-L-LOLA-3-RDR-V1.0, product
version V1.04), archived by the PDS Geosciences Node. LOLA fires at 28 Hz.
Each shot splits into five beams that land on the surface as a cross of five
spots. Each RDR orbit product is a fixed-record binary table with one 256-byte
little-endian row per shot (`lolardr.fmt`, 66 columns). This recipe emits:

| series | lolardr.fmt field | unit | role |
|---|---|---|---|
| `spot_radius_mm_i32` | `RADIUS_1..5`, LSB_INTEGER, START_BYTE 49 + 40(k-1) | mm from the Moon's centre | primary |
| `spot_range_mm_i32` | `RANGE_1..5`, 4-byte LSB integer, START_BYTE 53 + 40(k-1) | mm, two-way range (c/2 · time of flight) | primary |

Each orbit product becomes one sample per series. A sample holds every valid
spot of the orbit in shot order, with spots 1..5 in order inside each shot.
Both series keep the same spots in the same order.

    bash staging/nasa_pds_lola_rdr_spot_radius_range_i32/download.sh   # ~1.36 GB
    bash staging/nasa_pds_lola_rdr_spot_radius_range_i32/build.sh
    bash staging/nasa_pds_lola_rdr_spot_radius_range_i32/verify.sh

`discover.sh` documents how `sources.tsv` was resolved. It fetches directory
listings, the collection MD5 list, labels, and 24 × 16 KB range reads per
candidate orbit. `download.sh` does not run it.

## Scope

- **Phases.** The scope is the 28 phase directories of LRO's quasi-circular
  ~50 km polar mapping orbit:
  - `lro_no_01..13` (NOMINAL MISSION, 2009-09-15 .. 2010-09-16)
  - `lro_sm_01..15` (SCIENCE MISSION up to 2011-10-31)

  Their orbit products are 48.59-48.70 MB, about 190,000 shots or 113 min.
  `lro_sm_16` and later phases are excluded. There LRO moved toward the
  30 × 180 km elliptical orbit: products first shrink, then grow to ~51.2 MB
  from `lro_sm_18`, and the range spans a different interval. The 166
  extended-science phases (`lro_es_*`) are also excluded: their valid-spot
  fractions collapse (a probed ES-10 orbit kept about 4%).
- **One orbit per phase**, 28 orbits from 2009-10-04 to 2011-10-17. Within a
  phase, orbits are sorted by name and tried in bisection order (n/2, n/4,
  3n/4, ...). The first orbit whose 24-chunk range-read probe keeps at least
  40% of its spots is pinned. Four phases had a low-validity median orbit
  (0-29% kept spots) and fell back to rank 2 or 3. `sources.tsv` records the
  rank and the probe fraction for each phase.
- **Laser.** `INSTRUMENT_MODE_ID` shows LASER_1 for 18 orbits and LASER_2 for
  10. It is the same receiver, telescope, product version and range
  definition. The index records `laser` per sample.

## Spot policy (missing values, noise)

A spot k of a shot is kept iff all three conditions hold:

- `RADIUS_k != -1` (MISSING_CONSTANT)
- `RANGE_k != 4294967295` (MISSING_CONSTANT; RANGE_3 is declared
  LSB_INTEGER with -1, which is the same bit pattern)
- `SHOT_FLAG_k & 0xFF == 0`

`lolardr.fmt` says of the flag's low byte: "Any values other than 0 should be
regarded as an invalid measurement". The low-byte bits are: not ground,
transmit/receive leading or trailing edge missing, transmit energy invalid,
autoedit, and pointing not found. SHOT_FLAG bits 8-9 (RMU phase) and 16-31
(relative range uncertainty) are not invalidity flags and are ignored. No
thresholds on the values themselves are used for selection.

The following are fatal sanity checks, not filters:

- every kept radius lies in 1.72e9..1.76e9 mm
- every kept range lies in 1e7..2.5e8 mm and is below 2^31, so int32 storage
  is bit-identical to the source uint32
- every orbit keeps at least 30% of its spots
- in verify, |SC_RADIUS − RADIUS_k − RANGE_k · cos θ| < 1 km for at least 99%
  of kept spots, where θ = OFFNADIR_ANGLE / 20000 rad. Realized: 100% in
  every orbit; nadir residuals are within about ±45 m.

## Realized output

| | |
|---|---|
| orbits | 28, 2009-10-04T15:04 .. 2011-10-17T20:17, 5,320,644 shots |
| spots | 26,603,220: kept 14,891,249 (55.98%), missing 11,475,005 (43.13%), flagged 236,966 (0.89%) |
| kept fraction per orbit | 0.4125 (lro_sm_11) .. 0.6255 (lro_sm_02) |
| kept per spot 1..5 | 2,228,748 / 2,175,567 / 4,216,751 / 4,094,920 / 2,175,263 |
| primary samples | 56 (28 per series), 29,782,498 values, 119,129,992 bytes |
| values per sample | 391,860 .. 594,067, median 557,979 |
| radius | 1,729,991,331 .. 1,744,627,311 mm |
| range | 29,227,370 .. 73,655,275 mm |
| distinct values | at least 93% of values in every sample |

Most dropped spots are MISSING, i.e. no ground return was detected. Long
stretches of some orbits have no returns, and spots 3 and 4 return about
twice as often as spots 1, 2 and 5. Per-orbit counts are in the index:
`spots_missing`, `spots_flagged`, `kept_fraction`, `kept_per_spot` and
`laser`.

**Off-nadir slews.** 12 of the 28 orbits contain spacecraft off-nadir
pointing of 2.3-27.4° (LRO rolls, e.g. for camera targeting). During a slew,
RANGE grows by 1/cos θ while RADIUS still follows the terrain. This is
published source behaviour. The values are kept and verify's geometry check
corrects for it.

## Format and conversion

The offsets are PDS3 START_BYTE − 1. The parser reads a struct with RADIUS_k
`<i` at 48 + 40(k-1), RANGE_k `<I` at 52 + 40(k-1), and SHOT_FLAG_k `<I` at
76 + 40(k-1). (The candidate card listed 72 for SHOT_FLAG; that offset is
GAIN_k. 76 is correct per `lolardr.fmt`.) Download and build re-check these
offsets against the pinned `lolardr.fmt`.

Verify uses its own fmt parser and a flat uint32 word view of each file. The
parser self-test writes synthetic records at the fmt START_BYTEs, with filler
in all other bytes. Values are copied unchanged and written as raw
little-endian int32, one `<stem>.i32` file per orbit per series.

## Notes for review

- **Correlation.** Radius and range are tightly related: for a near-nadir
  altimeter, radius ≈ spacecraft radius − range. Range is the raw
  time-of-flight observable, a smooth altitude curve plus topography at
  ~3e7-7e7 mm. Radius is the geolocated product, topography about a
  1.737e9 mm datum. The two have different value distributions and byte
  structure. If one primary series is preferred, `spot_range_mm_i32` can
  become auxiliary.
- **Slews.** Off-nadir slews (see above) put short, smooth excursions into
  the range series of 12 orbits. They were not filtered out, because the
  documented flags do not mark them invalid.
- **Gaps.** Dropping invalid spots means consecutive values are not always
  equally spaced in time or position. The pattern of dropped spots varies
  along each orbit.
- **License.** NASA SMD open-data policy, on the same basis as the accepted
  GRAIL KBR1C and MOLA MEGDR recipes from the same host. No use restriction
  appears in the labels, `lolardr.fmt` or `aareadme.txt`.
