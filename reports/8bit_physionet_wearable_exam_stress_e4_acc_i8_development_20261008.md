# PhysioNet Wearable Exam Stress E4 wrist accelerometer int8: development report

## Outcome

Accepted `physionet_wearable_exam_stress_e4_acc_i8`, built from the immutable PhysioNet Wearable Exam Stress Dataset 1.0.0 (Amin, Wickramasuriya and Faghih, 2022; doi:10.13026/kvkb-aj90).

This is the corpus's first Empatica E4 family and its first 8-bit accelerometer family, locally or downstream. Wrist tri-axial accelerometry already exists at 16 bits (`zenodo_newcastle_geneactiv_wrist_accel_i16`: GENEActiv, ±8 g, 12-bit counts, 85.7 Hz). So this is new content in a known modality, not a new modality. The zlsim breadth verdict is OK: the nearest family is downstream `pathmnist_images`, at feature distance 0.0842. PhysioNet was over the per-archive host cap; the user approved the override on 2026-10-08.

## Source and rights

- Source: official anonymous PhysioNet open-data S3 mirror, `https://physionet-open.s3.amazonaws.com/wearable-exam-stress/1.0.0/`, byte-identical to `physionet.org/files/wearable-exam-stress/1.0.0/`.
- Fetched files:
  - the 30 `data/S{1..10}/{midterm_1,midterm_2,Final}/ACC.csv` files, 137,767,322 B in total;
  - `SHA256SUMS.txt` (22,163 B, 244 entries);
  - `LICENSE.txt` (20,402 B).
- Pinning: each fetched file is pinned by size and SHA-256, and the set of ACC.csv files listed in SHA256SUMS must equal the pin set exactly.
- License: Open Data Commons Attribution License v1.0 (ODC-By-1.0), open access. The project page states "Anyone can access the files, as long as they conform to the terms of the specified license. License: Open Data Commons Attribution License v1.0". `download.sh` saves that page and requires the statement, the DOI and "Empatica E4". The release's own `LICENSE.txt` (ODC-By text) is hash-pinned.
- Safety: IRB-approved (University of Houston), de-identified recordings. Timestamps are date-shifted and subjects are labeled S1..S10. Grades, demographics and the physiological channels are never fetched.

## Shape and conversion

Each natural record is one exam session's `ACC.csv`. Row 1 is the session start time and row 2 is the 32 Hz rate, each repeated in three columns. Every following row is one `x,y,z` reading of signed counts of 1/64 g over the E4's ±2 g range.

The build checks that the start-time row has three equal values and that the rate row is 32.0, then drops both rows. Every data row must be exactly three integers in -128..127; anything else is fatal. The values are written as interleaved signed int8 `x0,y0,z0,x1,…`, unchanged: no scaling, filtering, resampling, axis reordering or trimming.

Gravity is included. The -128 and 127 rails are genuine saturation and are kept. The devices recorded before and after each exam (midterm sessions run 2.8 to 3.9 h, finals 3.9 to 7.2 h), and that time is kept as well.

## Accepted output

- Primary series: `e4_wrist_acc_xyz_i8` (native_numeric, int8)
- Samples: 30, one per session
- Frames: 14,185,278 (123.1 h at 32 Hz)
- Primary values: 42,555,834
- Primary bytes: 42,555,834
- Minimum sample: 956,304 values (S8_midterm_2)
- Median sample: 1,205,433 values
- Maximum sample: 2,478,924 values (S3_Final)
- Rail values (-128 or 127): 6,693
- static_frame_fraction (frames identical to the previous frame): 0.149 to 0.463
- Most-common-value fraction: 0.028 to 0.112
- Aggregate SHA-256 over per-sample digests: `71e32a2a9f18ac6a2b53e2807f5ef7fcae1b84e89cc654b754bf97c2c399793e`

## Judge checks

- **Mechanics:** I ran `tools/autocollect/gate.py`. It passed with no warnings: 30 samples, 42,555,834 values and bytes, median 1,205,433, width 8.
- **Reproducibility:** I ran `verify.sh`, which passed.
  - It decodes independently with the csv module, compares bytes, every index field, the stats and the aggregate hash, checks the manifest totals and rejects stray files.
  - `build.sh` reads only local downloads.
  - `download.sh` is curl-only, resumable and stall-bounded, and contains no credentials.
- **Bytes**, inspected with `struct` across all 30 samples:
  - Every session spans the full -128..127 range on every axis. Median vector magnitude is 62.2 to 65.4 counts per session (1 g at 1/64 g), so the unit claim holds.
  - All 256 codes occur and the odd-code fraction is 0.496, so there is no widened code lattice.
  - Order-0 entropy is 6.0 to 7.0 bits per byte; x-delta entropy is 2.0 to 3.7 bits.
  - An independent decode of `S4_Final_ACC.csv` matches its sample byte for byte.
- **Duplication and fill:**
  - No duplicate sample prefixes, and none of 1,455 non-trivial 4 s windows repeats across sessions.
  - Identical-frame runs of 60 s or more cover 0.72% of all frames (longest 669 s, in S4_Final). The low-motion share is genuine wear, not off-device fill.
- **Rights:** I opened the saved project page and found the access policy, ODC-By v1.0, the DOI, a version list showing only 1.0.0, and IRB approval. `LICENSE.txt` contains the ODC-By text and is listed in the release SHA256SUMS.
- **Novelty:**
  - `novelty.py` on both source URLs, with terms empatica, wearable-exam-stress, exam stress, E4, accelerometer and wrist, found no prior recipe, registry, ledger or downstream entry for this source or device.
  - The type check found no 8-bit `inertial_vibration` family locally, and no instrument or archive match.
  - The downstream 8-bit list has no accelerometer family.
  - The driver's zlsim verdict is OK, with nearest feature distance 0.0842, above the 0.05 redundancy threshold.
- **Homogeneity:** one device model, one ±2 g range at 1/64 g, 32 Hz in every header, and one seated-exam protocol. The separate exercise-protocol `wearable-device-dataset` is not merged.
- **Volume:** the recipe takes the whole population (30 of 30 sessions), 42.6 MB of dense raw sensor data from 137.8 MB of CSV.
