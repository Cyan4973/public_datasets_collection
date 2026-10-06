# Monado SLAM Datasets Valve Index calibrated IMU float64 development

## Outcome

Accepted `monado_msd_valve_index_imu_f64` from the Monado SLAM Datasets (MSD) on Hugging Face (`collabora/monado-slam-datasets`, revision `74c07d42d980c55775dd0edc06e58c486b848be1`).

This is a new source for the 64-bit inertial modality. The only other local 64-bit inertial family is `har_smartphone_uci` (50 Hz smartphone, fixed 128-sample windows, ~8 significant digits). This recipe instead holds:
- continuous VR-headset IMU sessions from 3.5 s to 36.5 min;
- ~1 kHz sampling on the device clock;
- full-mantissa binary64 calibrated values.

The first build covered all 49 Valve Index sequences and was sent back for repair (cycle 1). Byte inspection showed that upstream applied the published Basalt accel/gyro correction once, twice or three times depending on the sequence. The repaired recipe keeps only the 30 single-correction sequences.

## Source and rights

- Source: the stored (method 0) `<seq>/mav0/imu0/data.csv` member of each sequence ZIP under `M_monado_datasets/MI_valve_index/`. Each member is range-fetched from the pinned revision.
- License: CC BY 4.0. Evidence at the pinned revision:
  - card front matter `license: cc-by-4.0`;
  - README introduction: "permissive license CC-BY 4.0 … use them for any purpose";
  - README License section: "Creative Commons Attribution 4.0 International License";
  - revision API: `gated=false`, `private=false`.
- `download.sh` re-checks all of the above. Access is anonymous; no credentials are used.
- Citation: de Mayo, Cremers, Pire, *The Monado SLAM Dataset for Egocentric Visual-Inertial Tracking*, IROS 2025.
- Privacy: only headset IMU readings are emitted. No images, audio or wearer identifiers.

## Shape and conversion

- **Natural record:** one recorded headset sequence. Its complete IMU stream becomes two primary samples:
  - `msd_valve_index_gyro_w_rs_s_f64`: rows×3, `w_RS_S` in rad/s;
  - `msd_valve_index_accel_a_rs_s_f64`: rows×3, `a_RS_S` in m/s².
- **Auxiliary:** device timestamps as int64 ns.
- **Conversion:** `float()` on shortest-round-trip decimal text recovers the exact published doubles. Values are written little-endian, row-major, in source order. No rows are dropped and nothing is widened locally.
- **Download validation:** each member range is checked for HTTP 206 with exact Content-Range, the local-header signature, name, method, sizes and the central-directory CRC-32.
- **MIPB08 split archive:** MIPB08 is a genuine 4-part split archive. Its member is read from `.z02` at the central-directory disk-start offset.
- **Scope:** MIO04–MIO16, MIPB01–MIPB08, MIPP01–MIPP06 and MIPT01–MIPT03.
- **Excluded:**
  - MIC01–MIC16 and MIO01–MIO03: the correction was applied two or three times. Their accel-x lattice steps are 0.0022610797 and 0.0021973218, and their gyro rest offsets are about −1× and −2× the published bias. They are excluded rather than inverted locally, because inverting would be a synthetic remap.
  - The HP Reverb G2 and Samsung Odyssey+ devices: different IMUs.
  - `data.raw.csv` and `data.extra.csv`.
- **Single-correction guards:**
  - `download.sh` pins the 19 excluded names and requires tree = sources ∪ EXCLUDED.
  - build requires accel-x lattice step 0.0023266877217 ± 1e-9 in every sequence.
  - verify recomputes that step independently and requires the gyro-x rest offset to stay below 0.0085 rad/s.

## Accepted output

- Sequences: 30. IMU rows: 9,026,215 (pinned in build).
- Primary samples: 60.
- Primary values: 54,157,290 float64.
- Primary bytes: 433,258,320:
  - gyro: 30 samples, 216,629,160 B;
  - accel: 30 samples, 216,629,160 B.
- Auxiliary timestamps: 30 samples, 72,209,720 B.
- Sample size in values:
  - minimum: 10,401 (MIO09, 3,467 rows);
  - median: 687,147;
  - maximum: 6,577,557 (MIPB08, 2,192,519 rows, 24% of all rows).
- Download: 1,204,756,112 B of member ranges (1,204,752,957 CSV bytes), plus about 0.2 MB of metadata.
- Accel-x lattice step range: 0.002326687721748044–0.0023266877217489323.
- Timestamps: 0 duplicate and 0 backward steps.
- Caveats, kept as published:
  - gyro saturates at about ±8.8 rad/s;
  - the information content of the calibrated values is below 64 bits per value;
  - MIPB08 dominates the row count.

## Judge checks

- **Gate:** `python3 tools/autocollect/gate.py staging/monado_msd_valve_index_imu_f64` → PASS, no warnings (60 samples, median 687,147 values, widths [64]).
- **verify.sh:** I ran `bash staging/monado_msd_valve_index_imu_f64/verify.sh` → exit 0 (52 s), `verify_ok sequences=30 primary_samples=60 primary_values=54157290 primary_bytes=433258320`. It includes a byte-identical independent re-derivation of every sample.
- **Download log** (`download.20261005_225127.log`): metadata_validation=ok (sequences=30, excluded=19), 19 out-of-scope cached members removed, 30 cache hits. The downloads directory holds only the 30 in-scope CSVs plus metadata.
- **My own stdlib byte inspection** (scripts under `/tmp/autocollect/monado_msd_valve_index_imu_f64/`):
  - **Accel-x:** identical lattice step in all 30 sequences, with 1,711–17,640 distinct values each.
  - **Gyro-x:** about 99.5% distinct (full Basalt gyro matrix, no lattice).
  - **Rest window** (5% lowest gyro norm): |a| = 9.549–9.574 m/s² in all 30. MIO04's overall median of 10.16 reflects motion, not a different scale. Gyro rest medians are within −0.0033…+0.0071 rad/s on every axis.
  - **Duplicates:** no duplicate SHA-256 among the primary samples; first timestamps are distinct.
  - **Value checks** (sampled components): 0 float32-exact values; CSV text equals the repr of the stored doubles.
- **Rights:** I opened the pinned card copy and the revision JSON myself.
- **Novelty:** I ran `novelty.py` with source terms (monado, valve_index, imu0, euroc, basalt) and modality terms (gyroscope, accelerometer, inertial, imu). It found no prior source match. `pipeline/candidates.tsv` has no accepted 64-bit IMU family.
- **Credentials:** a grep of every script finds no token, auth header or API key. build and verify read only local files.
- **Known documentation nit (not blocking):** the manifest's `[processing].deterministic_notes` still claims verify checks "every distinct accel-x value on the single-correction lattice". The builder dropped that check because float32-rounded raw readings drift off the lattice, and replaced it with the gyro-x rest-offset guard, which the notes do not mention. The README describes the guards correctly. A maintainer should change the parenthetical to "(plus a gyro-x rest-offset guard below 0.0085 rad/s)" in a follow-up edit.
