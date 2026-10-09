# GRACE-FO L1B RL04 hybrid-transplant accelerometer (ACH1B) float64 development

## Outcome

Accepted `gracefo_l1b_ach1b_transplant_accelerometer_f64`. It is the first spaceborne electrostatic-accelerometer family in the corpus: daily 1 Hz non-gravitational linear accelerations of GRACE-FO 2 (GRACE D) from JPL's Level-1B RL04 product ACH1B, "GRACE-FO Level-1B Hybrid Transplant Accelerometer Data".

It is distinct from the accepted `gfz_gracefo_fgm_acal_bnec_f64`. That recipe is a GFZ-produced platform-magnetometer CDF product (B_NEC in nT), from a different directory tree on the same ISDC host. This recipe uses JPL Level-1B ASCII accelerometer data (m/s²). This is the second acceptance from `isdc-data.gfz.de` in this effort; a third needs the user's sign-off.

Scope differs from the card. The card proposed the ACX tarball line for 2023 Q1. The builder found that the ACX line mixes the L1A inputs behind ACH1B (ACC1A, ACH1A, ASO1A, AFO1A, ACT1A, switching from AFO1A to ACH1A on 2023-03-01). JPL's newer ACX2 line (issued from 2024-09) builds every ACH1B day from ACH1A with one software build. The product (ACH1B, GRACE D, RL04) is unchanged; only the tarball line and date window differ. The judge accepted the change: it improves homogeneity and spreads the samples over 3.5 years instead of one quarter.

## Source and rights

- Source: JPL GRACE-FO Level-1B RL04 ASCII (PO.DAAC `GRACEFO_L1B_ASCII_GRAV_JPL_RL04`, DOI 10.5067/GFL1B-ASJ04; in-file id 10.5067/GFJPL-L1B04), mirrored anonymously at `https://isdc-data.gfz.de/grace-fo/Level-1B/JPL/INSTRUMENT/RL04/`.
- Files: 97 daily `gracefo_1B_<date>_RL04.ascii.ACX2.tgz` tarballs, pinned in `sources.tsv` by name, size, Last-Modified, ETag and SHA-256. Total 617,255,766 bytes.
- Member integrity: the md5 of every tar member is checked against JPL's in-tar `checksum` member in download, build and verify.
- License: CC0-1.0. Every ACH1B header names `creator_institution: NASA/JPL`, `publisher: PO.DAAC` and the NASA Earth Science data-information-policy URL; that URL now returns 404. Its successor, the NASA Earthdata Data Use Guidance, states that "data provided from a NASA-led mission are licensed as Creative Commons Zero (CC0)" and "there are no restrictions on the use of these data" unless marked otherwise. No restriction is marked. The ISDC README says the data are "produced by NASA/JPL" and adds no terms. The MODIS recipes are precedent for this license basis. Cite the DOI.

## Shape and conversion

- Natural record: one daily `ACH1B_<date>_D_04.txt` member, stored as a float64 array `[records, 3]`, row-major, interleaved (lin_accl_x, lin_accl_y, lin_accl_z) per 1 s epoch.
- Decoding: the member is streamed with `tarfile`. The YAML header is checked for title, platform GRACE D, product_version 04, DOI, license URL, ACC1A input `ACH1A_<same date>`, and software `V04.10.2020-11-09-82-gd120e-dirty`. Column positions are taken from the header variables list and cross-checked against each "Nth column" comment.
- Row rules: each row must sit on the 1 s lattice of its UTC day, and the row count must equal `num_records`. Values are parsed with `float()` and must be finite with |a| < 1e-4.
- Excluded:
  - `ang_accl_*`, which is zero on every row of every day
  - the `acl_*_res` model residuals
  - `qualflg`: nonzero on 31.6% of rows, mostly the CLK1B clock-extrapolation bits. It is counted per sample and no rows are dropped.
  - `gps_time` and `GRACEFO_id`
  - the AC01B/AC11B thruster-model products
  - ACU1B, an older 2023-03 "updated transplant" near-duplicate present in the five Jan–Feb 2023 tarballs, made with different software
  - the `.rpt` reports
- Representation: `derived_operational_numeric`. ACH1B is JPL's pinned L1B product, transplanted from GRACE C accelerometer data for GRACE D's degraded instrument and consumed as-is by gravity-field processing. Locally it is only parsed from its published 16-significant-digit ASCII to binary64.
- Selection: every 12th ACX2 day of the 1,155 between 2023-01-01 and 2026-06-30 (21/30/31/15 days in 2023/2024/2025/2026). ACX2 has no 2023-03..06 tarballs.

## Accepted output

- Primary samples: 97 (all complete, 86,400 rows each; no partial days)
- Primary values: 25,142,400
- Primary bytes: 201,139,200 (2,073,600 per sample)
- Median sample: 259,200 values
- Ranges: X −1.25e-6..3.19e-7 (only two days go below −5e-7), Y 9.98e-6..1.093e-5, Z −2.98e-7..6.6e-8 m/s²
- Distinct values: 86,400 per component per day
- Download: 617,255,766 bytes (about 33% kept)
- Aggregate decoded SHA-256 (sample files in date order): `0046004cd03852873767962e981074eb149edfd09b944af4a0a58f820010a9de`
- Breadth (zlsim): OK. The family's own held-out compression ratio is 1.459. The nearest family is `orex_ola_l2_lidar_point_xyz_f64` at distance 0.035 but 6.8% compression loss, then `naif_mro_sc_bus_attitude_ck_f64` (0.072, 21.9%), `gfz_gracefo_fgm_acal_bnec_f64` (0.085, 6.9%) and `monado_msd_valve_index_imu_f64` (0.092, 7.5%).

## Judge checks

- `python3 tools/autocollect/gate.py staging/gracefo_l1b_ach1b_transplant_accelerometer_f64`: PASS, no warnings.
- `bash staging/.../verify.sh` run by the judge: `verify_ok samples=97 bytes=201139200 values=25142400`, with a byte-for-byte independent re-derivation of every sample from its tarball.
- The judge read `build.sh` and `scripts/ach1b.py`: local files only, no network code, no credentials.
- Bytes: the judge decoded 8 samples spanning 2023-01..2026-06 with `struct`.
  - Physically plausible ranges per component.
  - No value exactly representable in float32, so the width is honest.
  - No zero deltas and no exact-linear runs.
  - The low mantissa byte takes all 256 values (max share 0.0042).
  - The first rows of 2024-08-25 match the source text.
- Lineage: the judge read the full ACH1B header of 2024-08-25. In 2023-01-13 the judge compared ACH1B with ACU1B and confirmed that ACU1B is a distinct, older near-duplicate that is correctly excluded.
- Homogeneity: the judge scanned all 97 ACH1B `.rpt` files and header dates. All share software build time 2024-01-09, and the residual statistics stay steady (~2–4e-8 / ~5–7e-9) with no regime step.
- Rights: the judge fetched the NASA Earthdata Data Use Guidance (CC0 statement), the PO.DAAC dataset page (no restriction; DOI citation) and the ISDC RL04 README ("produced by NASA/JPL").
- Novelty:
  - `novelty.py --url` (ISDC and PO.DAAC URLs) found a same-host match only with the GFZ magnetometer recipe.
  - `--terms` found no other GRACE-FO accelerometer or L1B material locally or downstream.
  - `--type inertial_vibration --instrument ... --archive ...` found no shared instrument line or archive.
