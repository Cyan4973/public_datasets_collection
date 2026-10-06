# Monado SLAM Datasets — Valve Index calibrated IMU (float64)

Complete calibrated inertial streams from the Valve Index VR headset in the
[Monado SLAM Datasets (MSD)](https://huggingface.co/datasets/collabora/monado-slam-datasets)
(Collabora / TU Munich; IROS 2025). The recipe covers the **30 Valve Index
sequences whose published `imu0/data.csv` carries the Basalt IMU correction
exactly once**. For each one it fetches only the sequence's
`mav0/imu0/data.csv` (EuRoC/ASL format, ~1 kHz, device clock) out of the
multi-GB sequence ZIP by HTTP byte range. It then emits:

| series | role | per-sequence sample | content |
|---|---|---|---|
| `msd_valve_index_gyro_w_rs_s_f64` | primary | rows × 3 float64 LE | angular velocity `w_RS_S_{x,y,z}` [rad/s] |
| `msd_valve_index_accel_a_rs_s_f64` | primary | rows × 3 float64 LE | specific force `a_RS_S_{x,y,z}` [m/s²] |
| `msd_valve_index_imu_timestamp_ns_i64` | auxiliary | rows int64 LE | device timestamp [ns] |

One natural record = one recorded headset sequence. Its complete IMU stream
becomes one gyro sample and one accel sample. Units never mix inside a sample;
this follows the gyro/accel split used for translation/quaternion in
`tum_rgbd_groundtruth_pose_f64`.

## Source, revision and license

- Repository: `collabora/monado-slam-datasets` on Hugging Face, public and
  not gated. Every URL pins revision `74c07d42d980c55775dd0edc06e58c486b848be1`.
- License: **CC BY 4.0**. Evidence at the pinned revision:
  - card metadata `license: cc-by-4.0` (README front matter; the HF API reports
    `cardData.license = cc-by-4.0`, `gated = false`);
  - README introduction: "The dataset has a permissive license CC-BY 4.0,
    meaning you can use them for any purpose you want, and only a mention of
    the original project is required.";
  - README License section: "This work is licensed under a Creative Commons
    Attribution 4.0 International License."
  `download.sh` re-checks all three before fetching any member.
- Citation: M. de Mayo, D. Cremers, T. Pire, *The Monado SLAM Dataset for
  Egocentric Visual-Inertial Tracking*, IROS 2025, pp. 13111–13118,
  doi:10.1109/IROS60139.2025.11247240.

## Scope: 30 single-correction sequences

Kept (`M_monado_datasets/MI_valve_index/`):

- `MIO_others`: MIO04–MIO16 (13). This includes the short MIO09 (3,467 rows,
  3.5 s), MIO10 (7,632 rows) and MIO11 (10,970 rows).
- `MIP_playing`: 17 sequences
  - Beat Saber MIPB01–MIPB08 (8)
  - Pistol Whip MIPP01–MIPP06 (6)
  - Thrill of the Fight MIPT01–MIPT03 (3)

**MIPB08 is a split (multi-disk) archive**, not a damaged one. The tree holds
`MIPB08_beatsaber_long_session_1.z01`, `.z02`, `.z03` (18,253,611,008 B each)
and the final `.zip` (11,451,043,612 B), which carries the ZIP64 end records
(disk 3) and the central directory. Its central-directory entry for
`imu0/data.csv` names disk-number-start 1, so the member is read from `.z02` at
that part's local offset 15,042,639,768 (291,172,258 B, 36.5 min). It does not
cross a part boundary. Every other sequence is a single-file ZIP; the larger
ones are ZIP64.

### Excluded: 19 Valve Index sequences with the correction applied more than once

Byte inspection of the published `data.csv` shows that the upstream Basalt
accel/gyro correction was applied **once**, **twice** or **three times**,
depending on the sequence. The published correction is a lower-triangular
scale-misalignment matrix plus bias (`extras/calibration.raw.json`:
`calib_accel_bias[3] = -0.028198018`, `calib_gyro_bias[0:3] = (-0.0171, 0.0075, -0.0056)`).
Because the matrix is lower-triangular, `a_RS_S_x` depends only on the x count
and stays on a lattice. Each correction pass multiplies the lattice step by
0.971802 and subtracts the gyro bias once more.

| sequences | accel-x lattice step [m/s²] | passes | gyro rest offset [rad/s] |
|---|---|---|---|
| kept 30 (MIO04–MIO16, MIPB, MIPP, MIPT) | 0.0023266877 | 1 | x within ±0.0042 (≈ 0) |
| MIC02–MIC16, MIO01–MIO03 (18) | 0.0022610797 (= ×0.971802) | 2 | ≈ (+0.017, −0.007, +0.007) ≈ −1× bias |
| MIC01 (1) | 0.0021973218 (= ×0.971802²) | 3 | ≈ (+0.035, −0.015, +0.010) ≈ −2× bias |

The 19 over-corrected sequences (all 16 MIC calibration recordings plus MIO01,
MIO02, MIO03) are left out:
- Mixing them in would break the "one post-processing state" homogeneity.
- Undoing the extra passes locally would be a synthetic remap.
- `data.raw.csv` is not used either (see below).

`download.sh` pins the 19 names in `EXCLUDED` and requires that tree
sequences = `sources.tsv` ∪ `EXCLUDED`, so upstream drift is still detected.

Single-pass guards:
- `build.sh` requires each sequence's accel-x lattice step to equal
  0.0023266877217 within 1e-9. The step is the median of the gaps between
  distinct `a_RS_S_x` values, taken over gaps below 1.5× the smallest gap. It
  is recorded as `accel_x_lattice_step` in the index and ingest stats.
- `verify.sh` recomputes the step independently.
- `verify.sh` also requires the gyro-x rest offset (median over the 5 %
  lowest-norm rows) to stay below 0.0085 rad/s, half of one bias.
- A negative test confirmed that all three guards reject MIC01, MIC02, MIO01
  and MIO03.

Note on the step value: single-count gaps cluster at the pinned step ±4.6e-7,
because the raw readings passed through float32 before correction. The pinned
value is therefore the median single-count gap, not an exact closed-form
8·g/32768 × 0.971802.

Also excluded:
- HP Reverb G2 (`MG_*`) and Samsung Odyssey+ (`MO_*`). They use different
  IMUs, so they are left out to keep one sensor regime.
- `imu0/data.raw.csv`: raw readings printed with 10 decimals, before the
  correction.
- `imu0/data.extra.csv`: host arrival times, not measurements.
- Camera frames, ground truth and all other members, which are never
  downloaded.

### Why the calibrated `data.csv`

`data.csv` is the dataset's canonical EuRoC IMU stream. The upstream docs say
SLAM systems should consume it directly, with the Basalt correction already
applied during post-processing. For the kept 30 sequences it was applied
exactly once, as documented above. It is printed as shortest round-trip
binary64 text (16–17 significant digits, e.g. `-9.538571932353639`), so
`float()` recovers the exact published doubles. **Caveat for reviewers:** the
calibrated values are a fixed linear transform of quantized (and
float32-rounded) sensor readings. Their information content is therefore below
64 bits per value, even though the published representation is genuine
full-mantissa float64 and nothing is widened locally.

## Pipeline

1. `discover.sh` (run once while authoring; documents how `sources.tsv` was
   made). It lists the tree via the HF API, reads a 128 KiB tail of each
   archive (EOCD + ZIP64 locator/record), then a 1 MiB central-directory window
   around the middle. The writer emits gt/, cam0/, imu0/, cam1/ in that order,
   so imu0 sits near the middle; the full directory is fetched only as a
   fallback, and no fallback was needed. Finally it reads 1 KiB at the local
   header. All 49 Valve Index members resolve and are stored (method 0).
   Outputs:
   - `sources.all.tsv`: all 49
   - `sources.tsv`: the 30 in-scope rows, identical to the committed file
   Each row pins part file, size, LFS SHA-256, disk number, local-header
   offset and length, member size and CRC-32.
2. `download.sh`:
   - Validates repo identity, access and license, plus the tree (sources +
     EXCLUDED = all 49 sequences; same part sizes and LFS SHA-256).
   - Removes cached members of excluded sequences left by an earlier revision
     of this recipe.
   - Fetches one exact byte range per in-scope sequence (local header +
     member, 1,204,756,112 B in total).
   - Checks HTTP 206 with the exact `Content-Range` including the object size,
     `PK\x03\x04`, member name, method, sizes, the central-directory CRC-32 and
     the exact CSV header, then writes `downloads/<id>/<seq>.imu0_data.csv`.
   - Resume: `curl -C -` cannot be combined with `--range`. In a probe, curl
     then ignored the range and streamed to the end of the object. A stalled
     transfer is therefore resumed by requesting only the missing tail of the
     range and appending it (`--speed-limit 1024 --speed-time 120`, up to 12
     attempts, no `--max-time`).
   - `--max-filesize` = remaining range + 1 MiB, because curl also applies it
     to the ~1.2 KB HF redirect body.
3. `build.sh` / `scripts/msd_imu.py`:
   - Re-checks size and CRC-32 and parses with the `csv` module.
   - Requires the exact 7-column header, exactly 7 fields per row, digit-only
     timestamps and finite values.
   - Enforces the single-pass accel-x lattice step and pins the total of
     9,026,215 rows.
   - Keeps rows in source order and writes them as row-major little-endian
     float64 triples. Index min/max come from the stored doubles.
4. `verify.sh` / `scripts/verify_msd_imu.py`:
   - Uses an independent binary line-split parser, re-derives every sample and
     byte-compares it.
   - Checks CRC-32, SHA-256, index fields, min/max, per-component
     non-constancy, manifest `sample_count`/`total_size_bytes` and the floors.
   - Recomputes the lattice step, applies the gyro rest-offset guard, and
     asserts that no excluded sequence appears in `sources.tsv`, the index or
     the sample directories.
   - Physical sanity checks: median accelerometer norm within ±15 % of 1 g,
     median gyro norm < 5 rad/s, |w| ≤ 40 rad/s, median timestamp step ~1 ms.

Missing-value policy (build and verify agree): there are no missing values in
the source. Malformed, empty or non-finite fields fail the recipe, and no row
is dropped, reordered or imputed. Duplicate or backward timestamp steps are
kept and counted in the index (`duplicate_timestamp_steps`,
`backward_timestamp_steps`); more than 0.1 % of a sequence's rows fails the
recipe.

## Realized output (build of 2026-10-05)

- Download: 1,204,756,112 B of member ranges (smallest 474,997 B for MIO09,
  largest 291,172,258 B for MIPB08), plus ~0.2 MB of metadata.
- 30 sequences, 9,026,215 IMU rows (2.51 h at ~1 kHz).
- Primary: 60 samples, 54,157,290 float64 values, 433,258,320 B.
  - gyro: 30 samples, 216,629,160 B
  - accel: 30 samples, 216,629,160 B
- Auxiliary timestamps: 30 samples, 72,209,720 B.
- Per-sequence rows: 3,467 (MIO09, 3.5 s) to 2,192,519 (MIPB08, 36.5 min).
  The median primary sample is 687,147 values; min 10,401 (MIO09), max
  6,577,557 (MIPB08).
- Accel-x lattice step in all 30: 0.002326687721748044–0.0023266877217489323
  (pinned 0.0023266877217).
- Timestamps: 0 duplicate and 0 backward steps. The median step is
  999.73–1000.04 µs.
- All 54,157,290 source fields are shortest round-trip binary64 text
  (`repr(float(s)) == s`), and 0 of them are exactly representable as float32.

### Signal caveats (kept as published)

- **Gyroscope saturation.** The sensor's ±500 °/s range clips angular rate
  at about ±8.8 rad/s after calibration. 3,798 rows (0.042 %) have a
  component above 8.6 rad/s, mostly MIO04 (1,811), then MIPP01, MIO06, MIPP06
  and MIPB03. The accelerometer peaks at ±38.3 m/s² (≈ ±4 g). Clipped readings
  are real published measurements and are not altered.
- **Accelerometer norm.** The median norm per sequence is 9.54–10.16 m/s².
  The highest value is MIO04 (hand shooter, vigorous motion); all other
  sequences are 9.54–9.71.
- **Uneven samples.** MIPB08 alone is 24 % of the rows.

## Novelty and nearest families

- `har_smartphone_uci` (64-bit) is the only local inertial family. It holds
  UCI HAR smartphone signals at 50 Hz in fixed 128-sample windows, pre-filtered,
  printed with ~8 significant digits, in 18 split-level samples. This recipe
  is the same broad modality (inertial measurements) from a new source and
  sensor regime: a 1 kHz VR-headset IMU over continuous sessions of seconds to
  36 minutes, with full binary64 mantissas.
- `tum_rgbd_groundtruth_pose_f64` and `comma2k19_global_pose_ecef_positions_f64`
  are pose/position trajectories, not inertial readings.
- `novelty.py` found no match for monado / valve_index / imu0 / euroc in the
  recipes, registry, ledger or downstream mirror.

## Reproduce

```bash
bash staging/monado_msd_valve_index_imu_f64/download.sh
bash staging/monado_msd_valve_index_imu_f64/build.sh
bash staging/monado_msd_valve_index_imu_f64/verify.sh
# optional: re-derive sources.tsv from the live source (metadata only)
bash staging/monado_msd_valve_index_imu_f64/discover.sh
```
