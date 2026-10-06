# LUMO lattice-tower SHM accelerometer float32 development

## Outcome

Accepted `luh_lumo_tower_acceleration_f32`. It holds native single-precision vibration from the structural-health-monitoring (SHM) programme on LUMO, the Leibniz University Test Structure for Monitoring. LUMO is a 9 m steel lattice tower near Hannover with reversible damage mechanisms.

This is the corpus's first civil-structure vibration family and its first data from `data.uni-hannover.de`. The nearest existing families are honeybee hive vibration (`zenodo_accelerometer_pcm16`), headset IMU (`monado_msd_valve_index_imu_f64`), smartphone body acceleration (`har_smartphone_uci`), seismic waveforms (`seismic_waveform_i32`) and urban fibre-optic distributed acoustic sensing (`zenodo_spica_urban_das_f32`). None of them is a structural accelerometer array. Novelty kind: new source.

## Source and rights

- Source: Research Data Repository of Leibniz Universität Hannover, CKAN package `lumo` (id `93b52576-6a5a-4ce9-8c27-a0372590f7b0`), DOI 10.25835/0027803. Published by the Institut für Statik und Dynamik (Wernitz, Hofmeister, Jonscher, Grießmann, Rolfes).
- Resources: the six single-file exemplary ZIPs (`exemplary_datasets_{dam6,dam4,dam3}_{111,010}.zip`, 559.8 to 680.2 MB each, published 2025-05-07). The split multi-part monthly archive is not used.
- License: CC BY 3.0. The evidence:
  - CKAN `license_id = CC-BY-3.0`, `isopen = true`.
  - The landing page shows "License Creative Commons Attribution 3.0", schema:license `https://creativecommons.org/licenses/by/3.0/` and the Open Definition badge.
  - The dataset README states that only the meteorological data (owned by IMUK) are password-gated, "because of legal reasons". The structural data are open, and no meteorological data are used.
- Transfer: 770,718,051 bytes of exact ZIP member byte ranges, never the full 3.8 GB.
  - Each ZIP's live central directory is re-validated before transfer.
  - Every chunk must come back as 206 with the requested Content-Range.
  - Each member is inflated, and its CRC32, size and data descriptor are checked.
  - The SHA-256 of each extracted `.mat` is pinned in `mat_sha256.tsv`.

## Shape and conversion

Each SHMTS file is one 10-minute acquisition. It holds a MAT v5 struct `Dat` whose `Data` field is a 990,600 x 22 `mxSINGLE` matrix, stored column-major. Columns 1-18 are accelerometers `accel01x..accel09y` (9 levels x 2 horizontal axes, unit `g`). The upstream README identifies the sensors as MEAS 8811LF IEPE accelerometers read by NI-9234 24-bit modules in an NI cDAQ-9189. The rate 1651.6129 Hz is exactly 51200/31, a native NI-9234 rate, so nothing was resampled.

A natural sample is one accelerometer channel of one record: 990,600 little-endian float32 values (3,962,400 bytes). These are the exact stored bit patterns. Excluded:

- strain01-03 (m/m) and temp01 (degC)
- the MCOS datetime objects
- the MAT subsystem element

Selection: the 3rd of the 5 files, in time order, in each of the 12 state folders. That gives 6 healthy records and one record for each damage state (DAM6, DAM4 and DAM3 at levels 111 and 010), spread from Oct 2020 to Jun 2021. All 60 records would be 4.28 GB, over the 1 GB cap.

Decoding is pure-stdlib Python (zlib/struct/array). It includes a synthetic self-test and a second, independent Data locator in verify.

## Accepted output

- Records: 12 (6 healthy and 6 damaged; states DAM3_010, DAM3_111, DAM4_010, DAM4_111, DAM6_010, DAM6_111 and healthy)
- Primary samples: 216 (12 x 18 channels), all 990,600 values
- Primary values: 213,969,600
- Primary bytes: 855,878,400
- Global range: -0.13825 to +0.12064 g
- Peak-to-peak per sample: 0.00074 / 0.023 / 0.238 g (min/median/max)
- Distinct values per sample: 650 / 7,971 / 18,135 / 32,668 / 96,352 (min/q1/median/q3/max)
- Per-channel lattice step: 5.65e-7 to 6.36e-7 g, the same across all records
- Distinct sample SHA-256s: 216 of 216
- Aggregate SHA-256 of all samples, concatenated in index order: `96b40fa65201b4a251976a9f411361b344e195dd94adf0907de0af0dc28eece8`

Known characteristics:

- **Two calm records are thin.** `06_DAM3_111/SHMTS_202103200708` and `11_Healthy/SHMTS_202106160038` carry only about 10-11 bits of signal (650 to 1,979 distinct values per channel).
- **Record 08 has impulses.** `08_DAM6_010/SHMTS_202105060712` contains physical impulse transients that hit several channels at the same sample index (kurtosis up to 1,338).
- **One start time is null.** In `01_Healthy` the `Time` field is an MCOS object, so its `record_start_time` is null in the index.

## Judge checks

- **Gate:** `python3 tools/autocollect/gate.py staging/luh_lumo_tower_acceleration_f32` passed with no warnings.
- **Verify:** I ran `bash staging/.../verify.sh` myself. It succeeded (216 samples, 855,878,400 B, 27 s). build.sh and verify.sh read only `.data/downloads`.
- **Download provenance:**
  - The download log shows the CKAN license and DOI check, central-directory validation for all 6 ZIPs, and size plus CRC32 checks for all 12 members.
  - download.sh's mtime predates that run.
  - `mat_sha256.tsv` was pinned after the download, on top of the CRC32 values pinned before it.
- **Independent decode:** my own minimal MAT walker (dims pattern, class-7 flags, miSINGLE tag of 87,172,800 B) matched accel01x and accel09y byte for byte in two records.
- **Bytes:**
  - The values sit on a clean per-channel lattice: step histogram dominated by 1.0, fractional residuals at 0 or 1.
  - No NaN, Inf or dropouts; the longest identical run is 4 values.
  - Lag-1 autocorrelation is 0.5-0.995 outside record 08.
  - In record 08 the spike clusters line up in x and y at level 9 (indices 74785, ~98520, 110671, 115461, 145431, 150246), which points to physical events.
  - Within-record correlation between channels is at most |r| 0.97 for adjacent levels in one windy record, and |r| < 0.15 between x and y at the same level. No duplicates.
- **Rights:**
  - I fetched the live landing page and read the stored CKAN JSON.
  - I extracted the README.pdf text with stdlib Python and found the scope of the meteorological-data gate.
  - No credentials in any script; no personal data.
- **Novelty:** `novelty.py` (URL host, DOI, dataset path, and SHM and vibration terms) found no URL match anywhere and no structural-vibration family locally or downstream.
- **Housekeeping:** a `scripts/__pycache__/` directory exists in staging. It is gitignored (`.gitignore` line 5) and must not be promoted.
