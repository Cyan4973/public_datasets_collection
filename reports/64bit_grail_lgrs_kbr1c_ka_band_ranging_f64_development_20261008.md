# GRAIL LGRS KBR1C Ka-band inter-satellite ranging float64 development

## Outcome

Accepted `grail_lgrs_kbr1c_ka_band_ranging_f64`. The recipe takes every Level-1B KBR1C Release-4 daily product of the GRAIL extended mission, 2012-08-30 to 2012-12-14 at a 2 s cadence: 107 products. It emits the published dual one-way Ka-band inter-satellite ranging observables between GRAIL-A and GRAIL-B as three float64 primary series:

- biased range (m)
- range rate (m/s)
- range acceleration (m/s²)

No family in the local or downstream corpus covers spacecraft-to-spacecraft microwave ranging. The nearest material is the GNSS carrier-phase and pseudorange family (NOAA CORS RINEX, COSMIC radio-occultation excess phase), so the novelty is a **new source** within carrier-phase ranging, not a new modality. The 90 primary-mission products use a 5 s cadence, a different sampling lattice, and were excluded rather than mixed in.

## Source and rights

- Source: NASA PDS Geosciences Node, `GRAIL-L-LGRS-3-CDR-V1.0`, volume `GRAIL_0101` (Release 5; KBR1C introduced in Release 4, 2014-04-01).
- Pinning:
  - The volume checksum list `grail_0101_230316.md5` (2,948,426 B) is pinned by SHA-256 `66193455e5258c971985dd7e2b352416504cddbd531cf3c845818fdaf43185ae`.
  - `sources.tsv` pins each product's served size, published MD5, header and data record counts, first/last TDB and label MD5.
- Download: 1,434,264,190 bytes in total (107 `.asc` products, 107 `.lbl` labels and the MD5 list).
- License: NASA-led mission data.
  - The manifest cites the NASA SMD Science Information Policy, the same basis as `orex_ola_l2_lidar_point_xyz_f64`.
  - science.data.nasa.gov/about/license states that NASA-led mission data "including observations, engineering, calibration, and auxiliary data are licensed as Creative Commons Zero" unless a file carries a restrictive notice, and that "There are no restrictions on the usage of these data."
  - The labels, `LGRS_CDR_DS.CAT` and `errata.txt` carry no restrictive notice.
- Citation: Kahan, D.S., GRAIL LGRS CDR V1.0, GRAIL-L-LGRS-3-CDR-V1.0, NASA PDS, 2012.

## Shape and conversion

Each natural record is one published daily CRLF ASCII product: a `KEY : value` header ending at `END OF HEADER`, then 20 whitespace-separated columns per 2 s epoch (DPSIS Table 43).

| Series | Column | Role |
|---|---|---|
| `kbr1c_biased_range_f64` | 2 | primary |
| `kbr1c_range_rate_f64` | 3 | primary |
| `kbr1c_range_accl_f64` | 4 | primary |
| `kbr1c_tdb_seconds_i64` | 1 (TDB s past J2000 noon) | auxiliary |

- **Conversion.** Each value is `float()` of the published 16–17 significant-digit decimal, packed as `<d`. The values are not float32-representable, so float64 is the native width.
- **No splicing or filling.** Records are never spliced or filled. Upstream interpolates gaps of up to 20 s; longer gaps are absent records.
- **Re-bias steps.** After a phase break, biased range restarts with a new unknown bias. These re-bias steps are source semantics and are counted per sample.
- **Flagged records.** Records with the calibration-slew flag are kept and counted.
- **Physical link.** Range rate and range acceleration are the published first and second derivatives. Each has its own scale and statistics, and each series alone clears the floor.

## Accepted output

| Item | Value |
|---|---|
| Products | 107 (2012-08-30..2012-12-14, all extended-mission KBR1C in the volume) |
| Records | 4,578,310 |
| Primary samples | 321 (107 per series) |
| Primary values | 13,734,930 |
| Primary bytes | 109,879,440 (36,626,480 per series) |
| Auxiliary bytes | 36,626,480 (TDB int64) |
| Values per sample | 13,373 to 43,200, median 43,200 (77 full days) |
| Distinct values | 100% in every primary sample |
| Biased range | -211,773.19 to +475,435.13 m (per-arc bias) |
| Range rate | -1.2263 to +1.1798 m/s |
| Range acceleration | -4.226e-3 to +3.446e-3 m/s² |
| Gaps | 38 on 30 days, 8,783 missing epochs, longest 996 s |
| Re-bias steps | 29 on 25 days |
| Calibration-slew records | 31,202 on 59 days; 0 other flag digits |
| Partial days | 2012_08_30 (starts 16:31:38), 2012_12_14 (ends 20:54:42) |
| Concatenated primary SHA-256 | `018188b69b8e41fea56b429540de9608d2b66b5b5eb59fe5a490dd6747fdc00b` |
| zlsim | OK |

zlsim nearest neighbours per series:

| Series | Nearest family | Distance | Loss | Redundant |
|---|---|---|---|---|
| biased range | CORS pseudorange | 0.0552 | 0.598 | no |
| range rate | ICON IVM ion drift | 0.0477 | 0.095 | no |
| range acceleration | SXS BBH strain modes | 0.0419 | 0.0271 | yes |

The recipe verdict needs only one non-redundant primary series.

## Judge checks

- **Gate:** `gate.py` PASS with no warnings.
- **verify.sh:** I ran it myself and it passed in 18 s, reproducing every total above. `build.sh` reads only `.data/downloads/`; curl appears only in `download.sh` and `discover.sh`. `verify_samples.py` uses its own parser. It re-checks size and MD5, re-derives all four samples byte for byte, and checks rate-to-range integration, index min/max, SHA-256s and manifest totals.
- **Tamper test:** in a scratch `DATA_DIR` I flipped one bit of `kbr1c_range_accl_f64/2012_11_05.f64`, and verify failed with "bytes differ from the independent re-derivation".
- **Bytes, with `struct` on 5 days spread over the mission and per-day statistics on all 107:**
  - Precision: about 90% of values carry 16 significant digits. No value in those five full samples round-trips through float32, and the low mantissa byte is populated.
  - Consistency: rate integrates to range except at the documented post-gap jumps (+89.3 km after 158 s on 08-30, -15.9 km after 966 s on 10-29, +34.3 km after 956 s on 12-10). Acceleration integrates to rate on 99.4–100% of steps.
  - Spread: acceleration std per day stays within 3.8e-4 to 9.4e-4 m/s². Rate std is 0.05 to 0.78 m/s, larger in the first week from orbit geometry. Acceleration exponents run 2^-9 to 2^-29.
  - Distinctness: all 428 sample SHA-256s are distinct and the top-value count is 1 in every primary sample.
- **Scope:** the volume MD5 list holds 197 KBR1C products (90 from March to May 2012, 107 from August to December 2012), and the recipe uses all 107. The dataset catalog confirms the column semantics. It puts 12-13 and 12-14 in the decommissioning phase, but they use the same product and cadence and their statistics match the other days. The errata note no KBR1C data issues.
- **Rights:** I fetched the SMD policy page, science.data.nasa.gov/about/license (CC0 for NASA-led mission data) and the dataset catalog (no restriction text). No credentials appear in any script.
- **Novelty:**
  - `novelty.py` URL and term search finds same-host baselines only, no downstream match, and GRACE-FO accelerometer and magnetometer recipes (different quantities).
  - `--type` and `--instrument` return 0 matches.
  - Archive gate: no autocollect acceptance comes from pds-geosciences.wustl.edu yet (gravity, MOLA and SHARAD are pre-effort baselines), so no sign-off is needed.
- **Minor note, not blocking:** verify does not re-apply the generous |value| plausibility bounds, but its inputs are MD5-pinned and re-derived exactly. Its float32 check samples the first 1,000 values; I checked whole samples.
