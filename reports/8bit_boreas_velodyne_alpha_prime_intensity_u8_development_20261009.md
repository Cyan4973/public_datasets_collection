# Boreas Velodyne Alpha Prime per-point intensity uint8: development report

## Outcome

Accepted `boreas_velodyne_alpha_prime_intensity_u8`. Each sample is one complete published lidar revolution from the roof-mounted 128-beam Velodyne Alpha Prime of the UTIAS ASRL Boreas test vehicle in Toronto. The sample holds the per-point calibrated return intensity, emitted at the sensor's native 8-bit width in firing order.

- **Novelty:** this is the first recipe from the Boreas bucket. The corpus already has lidar return intensity only as airborne LAS at 16 bits (`dc_lidar_2015_intensity_u16`). Its other spinning-lidar families carry geometry only: GOOSE VLS-128 xyz f32 and NCLT HDL-32E xyz u16.
- **Breadth (zlsim):** OK. The nearest family is `zenodo_pacbio_sequel_subread_ipd_codecv1_u8` at distance 0.0686 with compression loss 0.0243. That is compression-near but statistically distinct.

## Source and rights

- **Source:** public bucket `s3://boreas` (AWS Open Data Registry, us-west-2), served anonymously from `https://boreas.s3.amazonaws.com/`. It is not requester-pays.
- **License:** CC BY 4.0.
  - pyboreas `DATA_LICENSE.md` says: "The Boreas and Boreas Road Trip datasets are licensed under a Creative Commons Attribution 4.0 International Public License ("CC BY 4.0")."
  - The AWS ODR entry for `arn:aws:s3:::boreas` lists CC BY 4.0 and names the 128-beam Velodyne Alpha-Prime.
  - `download.sh` aborts if the license sentence disappears, and `verify.sh` re-checks the local copy.
- **Attribution:** UTIAS ASRL. Cite Burnett et al., "Boreas: A Multi-Season Autonomous Driving Dataset", IJRR 2023, arXiv:2203.10168.
- **Pinning:** 264 objects with key, size and S3 single-part MD5 in `sources.tsv`. The SHA-256 of every downloaded sweep is in `payload_sha256.tsv`.
- **Download:** 1,334,877,072 bytes.

## Shape and conversion

- **Scope:** all 44 top-level sequences `boreas-2020-11-*` .. `boreas-2021-11-*`, the original Alpha Prime release.
  - The 2022-08 sequences are excluded; they add an `aeva_without_intensity/` sensor folder.
  - The 2024/2025 Boreas Road Trip sequences are excluded; they add an `aeva/` folder.
- **Selection:** within each sequence, the sweeps are sorted by timestamp and indices floor((2k+1)n/12), k = 0..5, are taken. That is 264 of 460,284 sweeps (8,054–18,775 per sequence).
- **Natural record:** one `lidar/<timestamp_us>.bin` file, N × 6 little-endian float32 values (x, y, z, intensity, laser_number, time).
- **Conversion:** int(field 3) is written as one uint8 per point, in source order, one sample per sweep. Intensity is stored as an exactly integral float on the sensor's 8-bit calibrated-reflectivity scale (0–100 diffuse, 101–255 retroreflective), so the conversion is lossless and nothing is clamped.
- **Not emitted:** geometry, ring ID and time offset.
- **Policy:** non-finite fields, non-integral or out-of-range intensity or ring, and sizes that are not a multiple of 24 are fatal in download, build and verify.

## Accepted output

- Primary samples: 264 (6 × 44 sequences)
- Primary values and bytes: 55,619,878
- Sample size: minimum 158,874, median 214,646.5, maximum 232,168 values
- Values present: all 256. Per-sample distinct values: minimum 99, median 205, maximum 256
- Overall value shares: 0 = 8.19%, 1 = 6.96%, 2 = 6.47%; values ≤ 10 cumulative 53.3%; retroreflective (101–255) 0.85%
- Per-sample zero fraction: minimum 0.72%, median 6.17%, maximum 48.09%
  - The maximum is the first selected sweep of the 2021-01-26 snowstorm sequence.
  - Mode share ranges from 2.8% to 48.1%, median 7.8%.
- Aggregate SHA-256 of the samples, concatenated in index order: `fafd150f7b2263c9a3089229334bc492a0ec03cc605bf98e64b24fc14a3dcb42`

## Judge checks

- **Gate:** `gate.py` passed with no warnings.
- **Verify:** `verify.sh`, re-run by the judge, passed in 44 s. It re-decodes every point independently with struct, compares the bytes exactly, and checks the pinned MD5 and SHA-256 of all 264 payloads.
- **Structural scan of all 264 sweeps:**
  - Per-point time is monotone, so samples are in native firing order. 219 sweeps start with the VLS-128 firing sequence 4,53,102,23…; the others start with the same sequence minus missing returns.
  - All 128 rings appear in every sweep.
  - Revolution span is ±0.0516–0.0519 s, except one truncated published sweep at ±0.041 s and two at ±0.053/0.054 s.
  - Per-point timestamps are quantised two ways (~425 vs ~625 distinct times per sweep), and both occur inside the same sequences. Intensity statistics are the same for both (mean 16.5 vs 15.8, zeros 6.2% vs 6.1%), so this is a driver timestamping detail on a field that is not emitted.
- **Zeros:** zero-intensity points sit at real ranges (median 12–22 m, none under 0.5 m), so 0 is a genuine low-reflectivity return and not a no-return sentinel.
- **Histogram:** the 100/101 spikes and the tail to 255 match Velodyne calibrated reflectivity.
- **Near-duplicates:** none among 864,779 aligned 64-byte chunks with at least 8 distinct values.
- **Bucket probe:** exactly 44 sequences from 2020-11 to 2021-11. Aeva folders are present only in 2022+ sequences.
- **Rights:** the judge read the license text in the downloaded DATA_LICENSE.md and on the AWS ODR page. The scripts contain no credentials.
- **Novelty:** `novelty.py` was run for the URL, terms, vocabulary and breadth keys. There are no Boreas, instrument-line or archive matches. Lidar intensity exists elsewhere only at 16 bits, from airborne LAS.
- **Volume:** 55.6 MB is below the ~100 MB downstream sub-sample. It is in line with many accepted 8-bit families, the kept signal is large in absolute terms, and the 1/24 extraction ratio is unavoidable because intensity is interleaved in the float32 point records.
