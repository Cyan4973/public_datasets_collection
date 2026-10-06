# PDEBench 2D compressible Navier-Stokes turbulence (M=1.0) density, float32

This recipe collects mass-density fields from a 2D compressible Navier-Stokes
turbulence simulation in the PDEBench benchmark (Takamoto et al., NeurIPS 2022
Datasets and Benchmarks). The source is DaRUS DOI
[10.18419/darus-2986](https://doi.org/10.18419/darus-2986), version 8.0,
licensed CC BY 4.0. The source file is

`2D/CFD/2D_Train_Turb/2D_CFD_Turb_M1.0_Eta1e-08_Zeta1e-08_periodic_512_Train.hdf5`

DaRUS file id 164686, 88,080,392,528 bytes, MD5
`3f2c7376cde5fb072db0f9814f1c6992`.

The file holds 1000 independent simulations. They share one configuration:
Mach 1.0 turbulent initial velocity, shear and bulk viscosity 1e-8, periodic
unit square, 512 × 512 cells, and 21 saved steps at t = 0, 0.05, ..., 1.0.
The simulations differ only in their random initial velocity field. The
root datasets are `density`, `pressure`, `Vx`, `Vy` (each `(1000, 21, 512, 512)`
float32) and the `t-`, `x-` and `y-coordinate` arrays. Note that
`t-coordinate` has 22 entries (0 to 1.05), one more than the time axis.

## What is collected

- **Series:** `cfd_turb_m1_density_trajectory_f32` comes from `/density` only.
  Velocities, pressure and coordinates are excluded, so units and fields are
  never mixed.
- **Natural record:** one simulation trajectory, `/density[i]`, with shape
  `(21, 512, 512)` in time-step, x, y row-major order. That is 5,505,024
  float32 values, or 22,020,096 bytes per sample. The record is kept whole
  and not split into frames. Sample files are named
  `density_traj_NNNN.f32`, where NNNN is the simulation index.
- **Selection:** 40 evenly spaced simulations, i = 0, 25, 50, ..., 975. The
  total is 220,200,960 values, or 880,803,840 bytes. This stays under the
  1 GB cap while taking as many independent turbulent realisations as the
  cap allows.
- **Values:** the stored IEEE float32 values, unchanged. `/density` is
  `H5T_IEEE_F32LE` with contiguous, unfiltered storage, so a trajectory's
  bytes are exactly its typed values.

The t = 0 frame of every trajectory is expected to be exactly 1.0 everywhere,
because the simulations start from uniform density. This was confirmed in all
40 collected trajectories. It is a genuine part of the natural record
(1/21 of each sample) and is kept. The build records `t0_uniform_one` per
sample but does not fail on it either way. Frames t ≥ 1 are fully developed
compressible turbulence with shocks. Probes of trajectory 0 found about 260,000
distinct values per 262,144-cell frame and a density range of roughly 0.06 to
3.7.

## Bounded acquisition (re the `pdebench_sod6_shock_tube_f64` retry condition)

The earlier PDEBench attempt `pdebench_sod6_shock_tube_f64` was rejected. Its
small Sod file was degenerate, and its retry condition says not to download
the multi-gigabyte PDEBench files only to discard most of them.

**This recipe never requests the whole 88 GB file.** It issues only:

1. one catalog JSON request (license and file identity);
2. two 2,048-byte Range requests for HDF5 metadata (bytes `0-2047`, and
   `66060290048-66060292095`, where h5py placed the root link-name heap and
   the remaining object headers after the third large array);
3. forty Range requests of exactly 22,020,096 bytes each, at
   `2048 + i*22020096`.

The total download is about 881 MB, almost all of which is kept as samples.
The retry text's "float64" reflected that attempt's target width. This file is
native float32, and this is a different, non-degenerate file.

Each response must be `HTTP 206` with exactly the requested `Content-Range`
out of 88,080,392,528 bytes. The storage ETag is checked too. A `200`, or any
other range, is fatal, and `--max-filesize` stops a full-body response
before any bytes are written.

The DaRUS access API answers with a 303 to a presigned S3 URL that expires.
`download.sh` therefore goes back through
`https://darus.uni-stuttgart.de/api/access/datafile/164686` with
`curl --location` on every request, including every resume attempt.

Interrupted transfers resume manually. curl's `-C -` cannot be combined with
`-r`, so `download.sh` requests only the missing tail of each `.part` file and
appends it after the header check. It uses stall detection
(`--speed-limit 1024 --speed-time 120`), not a hard time limit.

## Validation

- `download.sh` checks:
  - the release state, the CC BY 4.0 license, the empty terms, and the
    file's name, directory, size and MD5 in the live catalog;
  - the SHA-256 of both metadata ranges, followed by a full parse of the
    HDF5 metadata (`scripts/pdebench_h5.py`, pure standard library);
  - for each trajectory: finite, strictly positive values, and at least
    10,000 distinct values in every frame from t = 1 on.

  Observed trajectory hashes go to
  `downloads/<id>/trajectory_sha256.observed.tsv`. The hashes from the first
  acquisition (2026-10-06) are pinned in this recipe's
  `trajectory_sha256.tsv`, and download, build and verify all enforce them.
  The storage ETag check is a hard failure only when no pins exist.
- `build.sh` works from local files only. It re-validates the metadata and
  every trajectory, copies each one to
  `samples/<id>/cfd_turb_m1_density_trajectory_f32/density_traj_NNNN.f32`, and
  writes `index/<id>/samples.jsonl` and `filtered/<id>/ingest_stats.json`.
  Min/max come from the stored float32 values.
- `verify.sh` (`scripts/verify_density.py`) works independently of the build:
  - it re-derives every byte range from the parsed HDF5 layout;
  - it byte-compares each sample with its fetched range;
  - it rescans the values through a separate code path for finiteness,
    positivity, non-constancy and the distinct-value check on frames t ≥ 1;
  - it rejects duplicate trajectories;
  - it cross-checks the index, the ingest statistics and the manifest's
    `sample_count` and `total_size_bytes`.

The HDF5 reader was self-tested on synthetic metadata covering continuation
blocks, version-1 and version-2 dataspaces, and rejection of big-endian
types, chunked layouts, filter pipelines, shape changes, overlapping
datasets and missing ranges. It was also checked against the live file,
where it agrees with an independent probe.

## Realized output (2026-10-06)

- **Download:** 881,090,712 bytes under `downloads/<id>/`, which is the 40
  trajectories plus 4,096 metadata bytes and the 277 KB catalog JSON. It took
  210 s, with no curl retries and no ETag warnings.
- **Samples:** 40 samples of 5,505,024 float32 values each, 220,200,960
  values or 880,803,840 bytes in total. The aggregate SHA-256 is
  `2af53ee815e601251e263ef10f9e1ce9f12c3a0272628ae4c492a1a0dcc963f1`.
- **t=0 frame:** uniform 1.0 in 40 of 40 trajectories.
- **Frames t ≥ 1:** at least 258,106 distinct values per 262,144-cell frame.
- **Density range:** 0.0279 to 4.835 across the 40 trajectories. Per-trajectory
  maxima run from 3.42 to 4.83.
- **Structure:** one sample checked in detail (trajectory 500) is spatially
  smooth, with lag-1 correlation 0.996 within a frame and 0.64 between
  consecutive frames. Its mean density stays 1.0, as mass conservation
  requires on a periodic domain. Yet `zstd -19` compresses its t ≥ 1 frames
  only 1.17×, so the material is neither trivial nor redundant.
- **Cross-check:** the first 4 MiB of trajectory 0 matches the SHA-256 of an
  independent author-phase probe of the same bytes.

## Run

```bash
bash staging/pdebench_2d_cfd_turb_m1_density_f32/download.sh
bash staging/pdebench_2d_cfd_turb_m1_density_f32/build.sh
bash staging/pdebench_2d_cfd_turb_m1_density_f32/verify.sh
```

All scripts honour `DATA_DIR` (default `.data`) and log to
`$DATA_DIR/logs/pdebench_2d_cfd_turb_m1_density_f32/`.

## Novelty and caveats

- **No CFD field family exists locally at 32 bits.** The nearest families
  are:
  - `ahmedml_cfd_surface_mean_pressure_f32`, which holds time-averaged
    surface pressure per polygon of an unstructured mesh;
  - `weatherbench2_era5_pressure_level_fields_f32`, which holds global
    reanalysis pressure-level volumes.

  This recipe instead holds direct simulation output of compressible
  turbulence: shock-laden, nondimensional, periodic, and time-resolved.
- **The layout is a dense Cartesian grid.** The The Well MHD-64 rejection
  argued that dense grids alone are not a new layout. What is new here is the
  material: an evolving compressible-turbulence density field. The layout
  itself is not new.
- **One configuration only.** Mixing in the M=0.1 file, the `Rand` files or
  other fields would add regimes. Those are excluded on purpose.
