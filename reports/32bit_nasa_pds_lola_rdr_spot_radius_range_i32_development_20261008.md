# LRO LOLA RDR per-spot lunar radius and laser range int32 development

## Outcome

Accepted `nasa_pds_lola_rdr_spot_radius_range_i32`. It collects per-laser-spot lunar surface radius and two-way laser range from the Lunar Orbiter Laser Altimeter (LOLA) Reduced Data Record. Both are published natively as 4-byte little-endian integers in millimetres and are kept at that width.

This is the first per-shot laser-altimeter material for the Moon in the corpus. It differs from both nearby families:
- `orex_ola_l2_lidar_point_xyz_f64`: Bennu body-fixed XYZ points, float64.
- `nasa_pds_mola_megdr_i16`: a gridded Mars DEM, not per-shot returns.

The 32-bit `laser_range` families present before this one are terrestrial float32 lidar and depth scans.

Novelty kind: new content in a known modality (laser ranging/altimetry).

## Source and rights

- Source: NASA PDS Geosciences Node, collection `lro-l-lola-3-rdr-v1/lrolol_1xxx` (DATA_SET_ID `LRO-L-LOLA-3-RDR-V1.0`, PRODUCT_VERSION_ID `V1.04`), anonymous HTTPS.
- Producer: LOLA Science Team, NASA Goddard Space Flight Center.
- Pins:
  - 28 orbit products, 1,362,084,864 bytes, with size, published MD5 (from `lrolol_1xxx_260915.md5`), record count and label MD5 per product in `sources.tsv`.
  - `lolardr.fmt` (26,916 bytes), SHA-256 `62855a2463d09e53a198cf06ccb22726d20ca5999a872da02bb93e290688505f`.
- License basis: NASA SMD open scientific data policy. SMD-funded research information is "made publicly available" and "Mission data are released as soon as possible."
  - The PDS LOLA page attaches no terms, registration or restriction to the RDR.
  - Same basis as the accepted `grail_lgrs_kbr1c_ka_band_ranging_f64` (same host), `nasa_pds_mola_megdr_i16` and `nasa_pds_sharad_radargram_f32`.
- No credentials; no personal data.

## Shape and conversion

- **Records.** Each RDR orbit product is a PDS3 fixed-length binary table: one 256-byte LSB row per 28 Hz shot, with 5 laser spots per shot.
- **Scope.** The 28 phase directories of LRO's quasi-circular ~50 km polar mapping orbit:
  - `lro_no_01..13`, NOMINAL MISSION;
  - `lro_sm_01..15`, SCIENCE MISSION.

  Excluded: `lro_sm_16+`, the transition to the elliptical orbit, and all 166 `lro_es_*` phases, whose valid-spot fractions collapse.
- **Selection.** One orbit per phase. Within a phase, products are tried in bisection order and the first whose range-read probe keeps at least 40% of spots is pinned: 24 phases at rank 1, two at rank 2, two at rank 3. The in-scope population is 9,699 products.
- **Fields.**
  - `RADIUS_k`: `<i` at byte offset 48+40(k-1).
  - `RANGE_k`: `<I` at 52+40(k-1).
  - `SHOT_FLAG_k`: `<I` at 76+40(k-1).

  All three are re-checked against the pinned fmt in download, build and verify.
- **Spot policy.** Keep spot k iff `RADIUS_k != -1`, `RANGE_k != 4294967295` and `SHOT_FLAG_k & 0xFF == 0`. The fmt says of the low byte: "Any values other than 0 should be regarded as an invalid measurement." There are no value thresholds; the plausibility bounds are fatal checks only.
- **Storage.** Values are copied unchanged as raw little-endian int32, in shot-major order with spots 1..5 inside a shot. Range is stored as int32 with an identical bit pattern, since every kept value is below 2^31. One sample per orbit per quantity.
- **Natural behaviour kept as published:**
  - Dropped spots make along-track spacing uneven.
  - 12 orbits contain off-nadir slews of 2.3-27.4 deg, during which range scales by 1/cos theta.
  - 18 orbits use LASER_1 and 10 use LASER_2 (same receiver, same range definition).

## Accepted output

| | |
|---|---|
| orbits | 28, 2009-10-04T15:04 .. 2011-10-17T20:17 |
| records (shots) | 5,320,644 |
| spots | 26,603,220 |
| spots kept | 14,891,249 (55.98%) |
| spots missing | 11,475,005 (43.13%) |
| spots flagged | 236,966 (0.89%) |
| kept fraction per orbit | 0.4125 (lro_sm_11) .. 0.6255 (lro_sm_02) |
| primary samples | 56 (28 per series) |
| primary values | 29,782,498 |
| primary bytes | 119,129,992 (59,564,996 per series) |
| values per sample | 391,860 .. 594,067; median 553,988 (manifest quotes the upper median, 557,979) |
| `spot_radius_mm_i32` | 1,729,991,331 .. 1,744,627,311 mm |
| `spot_range_mm_i32` | 29,227,370 .. 73,655,275 mm |
| distinct values per sample | 93.0% .. 98.8% |
| concatenated samples SHA-256 | `b0afc376b5ee1b4263279e74e1ac649eb5988f877df0684b44a8379075325a8a` |

Breadth (zlsim, 32-bit): verdict **OK**.

| series | own ratio | nearest family | distance | loss | redundant? |
|---|---|---|---|---|---|
| `spot_radius_mm_i32` | 2.2524 | era5_temperature_pressure_levels_f32 | 0.0486 | 0.0551 | no |
| `spot_range_mm_i32` | 2.2468 | downstream wmap_qq_weight_f32 | 0.0499 | 0.0174 | yes |

The range series is physically coupled to radius: radius ≈ SC_RADIUS − range·cos theta. It is retained as primary under the partial-redundancy precedent (GRAIL 1 of 3, Fermi LAT 4 of 5). Radius alone clears every floor. Downstream selection can weigh the range series accordingly.

## Judge checks

- **Gate.** `gate.py`: PASS, no warnings (56 samples, 29,782,498 values, 119,129,992 bytes, median 553,988).
- **verify.sh (re-run myself).** Exit 0. All 28 orbits re-derived byte for byte with verify's own fmt parser and uint32 word view. The geometry check |SC_RADIUS − RADIUS − RANGE·cos(OFFNADIR)| < 1 km passed for 100% of kept spots in every orbit, and the concat SHA-256 equals the manifest value. build.sh reads only local downloads; download.sh is curl-only, resumable and pinned.
- **Independent decode.** My own decoder with hard-coded offsets matches all 56 samples byte for byte (`/tmp/autocollect/nasa_pds_lola_rdr_spot_radius_range_i32/scripts/judge_decode.py`). I read the RADIUS_1, RANGE_1 and SHOT_FLAG_1 column objects in the pinned fmt myself.
- **Flag audit (kept spots).**
  - Bit 10 (TDC status invalid, "rare but serious") and bits 12-15 (manual-edit reasons): 0 occurrences.
  - Bits 16-31 (range uncertainty): all 0.
  - Bit 11 (FSW acquisition status, not an invalidity flag in the fmt): 6,154 of 14,891,249 (0.04%).
  - Isolated >500 m radius spikes: 1e-5..9e-5 of kept spots.
- **Value inspection (5 orbits × 2 series).**
  - Radius sd is 1.6-2.5 km about 1737.4 km.
  - Consecutive |delta| has median 1.8-3.6 m and p99 17-31 m; 3-5 km jumps sit only at no-return gaps.
  - Radius byte lanes have entropy 8.0/8.0/6.4-7.1 bits plus a constant 0x67 top byte. This is the native mm field; the values exceed 2^24, so the width is not widened.
  - Range top-lane entropy is 0.8-1.1 bits. Top repeat counts are 4-7, and mode_share is 0.
- **Rights.** Opened pds-geosciences `lola.htm` (no terms; producer is NASA GSFC) and the NASA SMD science-information policy page. The basis matches the accepted same-host GRAIL recipe.
- **Novelty.** Ran `novelty.py --url` for the data dir and `lola.htm`, `--terms`, `--vocabulary`, and `--type laser_range --instrument lro_lola --archive pds-geosciences.wustl.edu/lro/lro-l-lola-3-rdr-v1`. No LOLA, LRO or per-shot lunar altimetry exists in datasets, the registry, the ledger or downstream; instrument line and archive collection have 0 matches.
- **Cosmetic, not blocking.**
  - The manifest's median value count (557,979) is the upper median; the statistical median is 553,988.
  - One sentence in `deterministic_notes` states the geometry check without the cos term before stating the corrected form.
