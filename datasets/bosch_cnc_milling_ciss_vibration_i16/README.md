# Bosch CNC Milling CISS Tri-Axial Vibration Runs (Int16)

Each sample is the complete vibration recording of one machining operation on a
brownfield CNC milling machine. A Bosch CISS tri-axial accelerometer mounted
inside the machine sampled X, Y and Z at 2 kHz. The recipe takes every
published run of machines **M01** and **M02**: 1,163 runs covering 15
operations (OP00–OP14), six half-year timeframes (Feb 2019 to Aug 2021), and
both labels (1,102 `good`, 61 `bad`). Each run is emitted unchanged as one
little-endian **int16** `(n, 3)` row-major array (interleaved X, Y, Z).

- Source: <https://github.com/boschresearch/CNC_Machining> at commit
  `d60581d6a3ab6015dcc5488c3d76112bb8e1bcb1` (`main`, checked with
  `git ls-remote` on 2026-10-06)
- Paper: Tnani, M.-A.; Feil, M.; Diepold, K. *Smart Data Collection System for
  Brownfield CNC Milling Machines: A New Benchmark Dataset for Data-Driven
  Machine Monitoring.* Procedia CIRP 2022, 107, 131–136.
  <https://doi.org/10.1016/j.procir.2022.04.022>

## License

The upstream README (git blob `76e64e205cf889ae10a2ffdbb9c29e4205cb1738`) says:

> The dataset created for the research located in the directory [data](data)
> are licensed under a Creative Commons Attribution 4.0 International License
> (CC-BY-4.0).

The repository's `LICENSE` file (BSD-3-Clause) covers the loader code only, and
the recipe uses no upstream code. `download.sh` fetches that README by blob
SHA-1 and fails if the CC BY 4.0 sentence is missing. Attribution: cite the
paper above and credit Robert Bosch GmbH / Bosch Rexroth AG.

## Scope and subset

The full repository holds 1,702 run files (952,229,265 bytes of HDF5). Every
file's HDF5 header was read during authoring. At int16 the full set comes to
**1,071,607,440 bytes**, which is over the 1 GB cap. Per machine:

| Machine | runs | int16 bytes |
|---|---:|---:|
| M01 | 519 | 336,737,574 |
| M02 | 644 | 398,395,116 |
| M03 (excluded) | 539 | 336,474,750 |

The recipe keeps two whole machines, M01 and M02, and does not split any
timeframe, operation or label. That pair includes 61 of the 70 anomalous
(`bad`) runs, all six timeframes (M02 has all six; M01 lacks Aug 2020), and all
three container dtypes. Expected output: **1,163 samples, 367,566,345 values,
735,132,690 bytes**.

| Machine | Timeframe | good | bad | int16 bytes | container dtypes |
|---|---|---:|---:|---:|---|
| M01 | Feb 2019 | 59 | 19 | 48,119,814 | float32 74, float64 4 |
| M01 | Aug 2019 | 191 | 7 | 134,625,768 | float32 7, float64 191 |
| M01 | Feb 2020 | 58 | 0 | 37,472,256 | int64 58 |
| M01 | Feb 2021 | 152 | 2 | 96,269,784 | int64 154 |
| M01 | Aug 2021 | 25 | 6 | 20,249,952 | float64 2, int64 29 |
| M02 | Feb 2019 | 26 | 20 | 22,867,800 | float32 46 |
| M02 | Aug 2019 | 269 | 4 | 171,977,796 | float64 273 |
| M02 | Feb 2020 | 85 | 0 | 56,666,112 | int64 85 |
| M02 | Aug 2020 | 62 | 0 | 37,558,608 | int64 62 |
| M02 | Feb 2021 | 131 | 2 | 79,155,552 | int64 133 |
| M02 | Aug 2021 | 44 | 1 | 30,169,248 | int64 45 |

Run lengths in the selection are 26,793–317,440 rows, i.e. 80,379–952,320
values per sample, with a median of 264,192 values. Operations are covered
fairly evenly, with 53–102 runs each.

## Why int16 (width argument)

The publisher stored the same integer sensor readings in three HDF5 container
dtypes. Within the selection:

- **int64**: 566 files, every 2020–2021 run except two
- **float64**: 470 files, mostly Aug 2019
- **float32**: 127 files, mostly Feb 2019

The evidence that the content is 16-bit integers rather than real-valued
floats:

1. All 2020–2021 runs are stored natively as signed integers.
2. Authoring probes covered 18 files, one per machine × timeframe group for all
   three machines plus two larger runs, in all three dtypes. In every one of
   them every value was an exact integer, and the int16 copy converted back to
   the source dtype bit-exactly. Observed ranges were −6,308..5,391, with
   1.5k–2.1k distinct values per run and all residues mod 4 present, so the
   lattice step is 1.
3. The scale is the same in every container dtype. The Z axis carries a gravity
   offset of −1,014 to −1,050 counts in every probe file (X and Y means are
   near 0), so 1 g ≈ 1000 counts. This suggests milli-g readings, but the unit
   is an inference: the publisher does not document it.

The recipe does not assume the integer property; it enforces it per file.
`build.sh` keeps a file only if every value is finite, exactly integral, and
within [−32768, 32767]. A file that fails anywhere is dropped whole and listed
in `ingest_stats.json`; nothing is rounded, clipped or rescaled. A float −0.0
is the integer 0. It is counted, not dropped, and none was seen in the probes.
`verify.sh` re-applies the same rule through an independent conversion path.

Emitting float32, float64 or int64 instead would be a gratuitous widening of
16-bit integer content. Precedents: `zenodo_aegis_obd_pid_u8` keeps exact
integers at their native width, and `goose_vls128_lidar_scan_xyz_f32` dropped an
integer-valued float field rather than widen it. The series is declared
`native_numeric`, with this explanation in `representation_notes`.

### Realized result (build 2026-10-08)

The rule was checked against every value of all 1,163 files (367,566,345
values):

- 0 files dropped: none had a non-finite, non-integral or out-of-int16 value,
  a constant axis, or a duplicate output
- 0 negative zeros
- value range −6,668..6,074, about 20% of the int16 span
- 1,163 samples, 735,132,690 bytes, median 264,192 values per sample
- aggregate sha256
  `539cccdadbcc24eb4432ffa16096c842c0ae2ad80f468aa4a85efed80ce959d2`

Scale check over all samples, by machine and container dtype:

| Machine | dtype | runs | median Z mean | Z mean range | median X std | median distinct values |
|---|---|---:|---:|---:|---:|---:|
| M01 | float32 | 81 | −1037 | −1038..−1033 | 400.9 | 1798 |
| M01 | float64 | 197 | −1016 | −1038..−1013 | 398.8 | 1823 |
| M01 | int64 | 241 | −1014 | −1015..−1007 | 398.4 | 1817 |
| M02 | float32 | 46 | −1049 | −1051..−1049 | 406.3 | 1841 |
| M02 | float64 | 273 | −1032 | −1033..−1031 | 385.0 | 1940 |
| M02 | int64 | 325 | −1032 | −1034..−1028 | 389.8 | 1825 |

The gravity offset and the vibration spread match across dtypes to within
about 4%. The small shifts in Z mean follow timeframe (float32 is mostly
Feb 2019) rather than dtype, so no dtype carries a rescaling.

## Decode path (pure standard library)

`scripts/cnc_h5.py` implements the narrow HDF5 subset these files use:

- superblock v0 (8-byte offsets) and a symbol-table root group (v1 group
  B-tree, local heap, SNOD), which must contain exactly one link,
  `vibration_data`
- v1 object header of the dataset, with continuation messages (0x0010)
  supported; shared messages are rejected
- dataspace rank 2; IEEE float (LE, 4/8 bytes, standard field layout) or
  signed fixed-point (LE, full precision)
- filter pipeline with deflate (id 1) and optionally shuffle (id 2). Any other
  filter (fletcher32, szip, n-bit, scale-offset, third-party) is rejected.
  Per-chunk filter masks are honoured.
- layout v3 chunked with a v1 chunk B-tree (node type 1), any depth. The chunk
  grid must be complete. In all 1,702 headers the chunks are `(k, 1)` column
  segments, with k between 1,632 and 8,325 rows, so each chunk is inflated and
  scattered into the C-order `(n, 3)` array. This matches what `h5py`'s `f['vibration_data'][:]`
  returns.

In all 1,702 headers the dataset is `(n, 3)`, chunked, and deflate-only
(1,701 files at level 9 and one at level 7). No file uses shuffle or
fletcher32.

`scripts/selftest_cnc_h5.py` (run at the start of every build) writes synthetic
HDF5 files with a minimal pure-Python writer and checks byte-exact decoding of:

- float32, float64 and int64 data
- a 3-level chunk B-tree
- a continuation block
- partial edge chunks and 2-column chunks
- shuffle+deflate
- a filter-mask raw chunk and unfiltered chunks

It also checks that fletcher32, big-endian and unsigned types, missing chunks,
and a wrong dataset name are rejected.

## Output

- Samples:
  `samples/bosch_cnc_milling_ciss_vibration_i16/cnc_ciss_vibration_xyz_i16/<machine>/<operation>/<label>/<source stem>.bin`,
  raw int16 LE, `n*3` values. Run basenames repeat across `good` and `bad`, so
  the label is part of the path.
- Index: `index/bosch_cnc_milling_ciss_vibration_i16/samples.jsonl`. Besides
  the required fields, each row records the shape `[n, 3]`, the axes, the source
  path, size, blob SHA-1, container dtype and chunk shape, the machine,
  operation, label, timeframe and run index, the overall and per-axis min/max,
  the distinct-value count, the negative-zero count, and the sha256.
- Stats: `filtered/bosch_cnc_milling_ciss_vibration_i16/ingest_stats.json`,
  with kept counts per machine, timeframe, label, operation and dtype, every
  dropped file with its reason, totals, and an aggregate sha256.

## Validation

- **download.sh** fetches only the 1,163 files in `sources.tsv` plus the README,
  from `raw.githubusercontent.com/<commit>/…`. It never calls the GitHub API,
  which allows 60 unauthenticated requests per hour per shared IP. Each file
  must match its pinned size and git blob SHA-1, i.e. sha1 of
  `"blob <size>\0"` followed by the file bytes, which is the object id in the
  commit tree. Files are at most 1.6 MB, so each is fetched whole into a
  `.part` file and renamed after verification. Re-runs skip files that already
  verify. After the transfer, `scripts/validate_download.py` parses every
  file's HDF5 metadata and checks it against the pins: root links, shape, dtype,
  filters and a complete chunk grid.
- **build.sh** re-checks each identity, decodes every chunk, applies the width
  policy, drops files with a constant axis or a duplicate output, and writes
  samples, the index and the stats atomically.
- **verify.sh** re-decodes every source and converts it with `struct`,
  separately from the build's `array` round trip. It requires:
  - byte-identical samples and exact index fields
  - drop records identical to the build's
  - no stray files and no constant samples
  - the repository floors, the 1 GB cap, and manifest `sample_count` and
    `total_size_bytes` equal to the realized values
  - both labels and both machines present

`discover.sh` documents how `sources.tsv` was produced: one GitHub tree API
call, then 2 KB range GETs of every selected file's HDF5 header. The pipeline
does not run it. Rerun offline against the saved tree and heads, it reproduced
`sources.tsv` byte for byte.

## Novelty and homogeneity

- **Nearest local families:**
  - `zenodo_accelerometer_pcm16`: 60 one-second honeybee-hive vibration
    segments from a listening-oriented PCM16 WAV, 5.76 MB. Different domain,
    sensor and scale.
  - `luh_lumo_tower_acceleration_f32`: lattice-tower SHM accelerometers,
    float32.
  - `monado_msd_valve_index_imu_f64`: headset IMU, calibrated float64.
- No local or downstream recipe uses this source or machine-tool vibration
  (checked with `novelty.py`). This is a new source and domain within the
  existing accelerometer/vibration modality, not a new modality.
- **Homogeneity:** one sensor model, one 2 kHz rate, one integer scale (checked
  through the Z gravity offset in every container dtype), one machine class, and
  one `(n, 3)` layout. `good` and `bad` are process states within the same
  regime. Machines and timeframes differ in operating conditions, not in units
  or lattice.

## Caveats

- The unit (likely milli-g) and the CISS range setting are inferred, not
  documented upstream. The values are emitted exactly as published.
- Container dtype varies per file, even within a timeframe (e.g. M01 Aug 2021:
  2 float64, 29 int64). The recipe pins the dtype per file. It treats the
  differences as publisher export artifacts because the scale and lattice are
  identical across them.
- Hosting is a GitHub repository (no DOI or archive deposit). Integrity relies
  on the pinned commit and per-file git blob SHA-1.
- Labels are imbalanced: 61 `bad` vs 1,102 `good`.

## Reproduce

```bash
bash staging/bosch_cnc_milling_ciss_vibration_i16/download.sh   # ~642 MB, 1,164 small GETs
bash staging/bosch_cnc_milling_ciss_vibration_i16/build.sh
bash staging/bosch_cnc_milling_ciss_vibration_i16/verify.sh
```
