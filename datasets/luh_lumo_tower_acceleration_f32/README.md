# LUMO lattice-tower SHM accelerometer streams (float32)

Structural-health-monitoring (SHM) vibration of LUMO, the Leibniz University
Test Structure for Monitoring. LUMO is a 9 m steel lattice tower near Hannover
fitted with reversible damage mechanisms. The data acquisition system writes
one MATLAB file `SHMTS_<yyyymmddHHMM>.mat` per 10-minute acquisition. Each file
holds a 1x1 struct `Dat` whose `Data` field is a 990,600 x 22 `single` matrix
sampled at 1651.6129 Hz. Columns 1-18 are accelerometers `accel01x..accel09y`
(9 levels x 2 horizontal axes), with the unit recorded as `g` in
`ChannelUnits`. Columns 19-22 are `strain01-03` (m/m) and `temp01` (degC).

This recipe emits **one sample per accelerometer channel per 10-minute record**:
990,600 little-endian float32 values (3,962,400 bytes). These are the exact
stored binary32 bit patterns of one `Data` column.

## Source and license

- Package: <https://data.uni-hannover.de/dataset/lumo> (CKAN id
  `93b52576-6a5a-4ce9-8c27-a0372590f7b0`, DOI 10.25835/0027803), published by
  the Institut für Statik und Dynamik, Leibniz Universität Hannover.
- License: **CC BY 3.0**. The CKAN metadata has `license_id = "CC-BY-3.0"`,
  `license_url = https://creativecommons.org/licenses/by/3.0/` and
  `isopen = true`. The landing page shows "License: Creative Commons Attribution 3.0".
  Only the meteorological data are gated (by request), and they are not used.
  `download.sh` re-checks the license, `isopen` and the DOI on every run.
- Citation: Wernitz, S., Hofmeister, B., Jonscher, C., Grießmann, T.,
  Rolfes, R. (2021). *LUMO - Leibniz University Test Structure for Monitoring*.
  <https://doi.org/10.25835/0027803>.

## Scope and selection

The full monthly archive (August 2020 to July 2021, split multi-part ZIPs in
a vault directory) is not used. The package also publishes
six single-file **exemplary ZIPs** (560-680 MB each). Each contains two state
folders with five SHMTS files apiece:

| ZIP | folders |
| --- | --- |
| `exemplary_datasets_dam6_111.zip` | `01_Healthy`, `02_DAM6_111` |
| `exemplary_datasets_dam4_111.zip` | `03_Healthy`, `04_DAM4_111` |
| `exemplary_datasets_dam3_111.zip` | `05_Healthy`, `06_DAM3_111` |
| `exemplary_datasets_dam6_010.zip` | `07_Healthy`, `08_DAM6_010` |
| `exemplary_datasets_dam4_010.zip` | `09_Healthy`, `10_DAM4_010` |
| `exemplary_datasets_dam3_010.zip` | `11_Healthy`, `12_DAM3_010` |

That gives 60 records. All 18 accelerometer channels of all 60 would be
4.28 GB, over the 1 GB cap. The recipe therefore takes **the 3rd of the 5
files (chronological order) in each of the 12 state folders**. The result is
balanced: 6 healthy and 6 damaged records, every damage mechanism and level,
and records spread over October 2020 to June 2021 and over different times of
day. Realized output: 12 records x 18 channels = **216 samples, 213,969,600
values, 855,878,400 bytes**. `sources.tsv` pins every member with its CRC32,
compressed and uncompressed sizes, and exact ZIP byte range. `mat_sha256.tsv`
pins the SHA-256 of each extracted `.mat`, recorded after the first validated
download and checked by `build.sh` and `verify.sh`.

Discovery (`discover.sh`, `probe.py`) range-read the central directory of all
six ZIPs and the struct header of all 60 members. All 60 have Fs =
1651.6129032258063, dims 990600 x 22, the same 22 channel names, and unit `g`
for all 18 accelerometers. Folder names never repeat across ZIPs.

## Pipeline

1. `download.sh` checks the CKAN metadata (license, DOI, ZIP URLs and sizes).
   It re-reads each ZIP's central directory (last 64 KiB) and confirms the
   pinned CRC32, sizes and offsets. It then fetches each member's exact byte
   range (local header + DEFLATE data + data descriptor; 770,718,051 bytes in
   total, never the full 3.8 GB of ZIPs) with manual-offset resume and a
   206/`Content-Range` check on every chunk. Each member is inflated and its
   size, CRC32 and data descriptor are checked, then
   `scripts/lumo_mat.py check` validates the MAT schema. The range file is
   deleted after extraction unless `KEEP_ZIP_RANGES=1`.
2. `build.sh` runs the parser self-test on synthetic MAT files, then decodes
   each `.mat`. It walks the 128-byte header, the top-level `miCOMPRESSED`
   element, struct `Dat`, the MCOS datetime objects (skipped by element size),
   `Fs`, the `ChannelNames`/`ChannelUnits` cells and the `Data` `miSINGLE`
   payload (column-major). Columns 0-17 are written verbatim. A channel that
   contains NaN or Inf, or is constant, fails the build. The index
   `samples.jsonl` records the source member, state, channel, unit, Fs, start
   time, SHA-256, min/max, distinct-value count and smallest lattice step.
3. `verify.sh` re-derives every sample. A second, minimal Data locator walks
   raw tag sizes and must agree with the parser. Verify compares bytes,
   SHA-256, min/max and index fields, checks finiteness, non-constancy, at
   least 16 distinct values, duplicate content, stray files and manifest
   totals.

All decoding is pure-stdlib Python (`zlib`, `struct`, `array`).

## Things to know

- **ADC lattice / small amplitudes.** The stored floats are calibrated ADC
  readings. Each channel sits on its own lattice: one step is 5.65e-7 to
  6.36e-7 g depending on the channel (for example accel09x ≈ 5.66e-7 g,
  accel02y ≈ 6.33e-7 g), plus an offset. Each channel's step is the same
  across all 12 records; the apparent spread of ~1e-9 is float32 rounding.
  The motion is ambient (wind and traffic) vibration, so amplitudes are small.
  Realized per-sample statistics: peak-to-peak 0.0007 to 0.24 g (median
  0.023 g), global range -0.138 to +0.121 g, and 650 to 96,352 distinct values
  per 990,600-value sample (median 18,135, quartiles 7,971 / 32,668). Two calm
  records, `06_DAM3_111/SHMTS_202103200708` and
  `11_Healthy/SHMTS_202106160038`, use only 650-1,980 distinct values per
  channel, about 10-11 bits of real resolution in a 32-bit container. The
  windy records 05/07/09_Healthy use 36k-64k (median per record). Upstream
  publishes only these float32 values, not the integer ADC counts.
- **Start time.** `Time` is a UTF-8 char string in 11 of the 12 folders. In
  `01_Healthy` it is a second MCOS datetime object, so `record_start_time` is
  `null` for that record. The file-name stamp is always available in
  `source_member`.
- **Homogeneity.** All samples share one structure, DAQ, sampling rate, unit
  and sensor type. Damage states change the structure's modal properties, not
  the unit, scale or generation process. Strain and temperature columns are
  different quantities and are excluded.

## Run

```bash
bash staging/luh_lumo_tower_acceleration_f32/download.sh   # ~771 MB transferred, ~774 MB kept
bash staging/luh_lumo_tower_acceleration_f32/build.sh
bash staging/luh_lumo_tower_acceleration_f32/verify.sh
```

Logs are written to `.data/logs/luh_lumo_tower_acceleration_f32/`.
