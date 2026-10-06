# AhmedML Ahmed-Body Surface Time-Averaged Pressure (pMean), float32

Native float32 time-averaged surface pressure from the AhmedML CFD dataset
(Ashton et al. 2024): one complete `pMean` field per simulated Ahmed-body
geometry, one value per boundary polygon, for 50 of the 500 runs.

## Source

- Repository: <https://huggingface.co/datasets/neashton/ahmedml>, pinned at
  revision `02688c727cdb8dc8678e28abc6bbbb7e93c5fa15` (lastModified
  2026-08-18; the repository head as of 2026-10-06).
- Simulations: 500 parametric variations of the Ahmed car body, each run
  transiently with a hybrid RANS-LES model in OpenFOAM v2212 for about 80
  convective time units on ~20M-cell meshes. `run_<i>/boundary_<i>.vtp` holds
  the time-averaged surface fields (54-111 MB per run).
- License: CC BY-SA 4.0. The README front matter declares
  `license: cc-by-sa-4.0`, the HF API reports `cardData.license =
  cc-by-sa-4.0` and `gated = false`, and `LICENSE.txt` is the CC BY-SA 4.0
  legal code (sha256 `28a9529c7d0bb4dc51f4bf5c116a3d16ef247a052f7591466768ddf563fd1cf5`). `download.sh` re-checks all three.
- Attribution: Ashton, N., Maddix, D., Gundry, S., Shabestari, P. *AhmedML:
  High-Fidelity Computational Fluid Dynamics dataset for incompressible,
  low-speed bluff body aerodynamics*, arXiv:2407.20801 (2024);
  doi:10.57967/hf/5002. ShareAlike: if you share adapted material, you must
  offer it under CC BY-SA 4.0.

## What is collected

| | |
|---|---|
| Series | `ahmedml_boundary_pmean_f32` (primary, native float32, little-endian) |
| Quantity | OpenFOAM `pMean`: time-averaged kinematic static pressure p/rho (m^2/s^2) on each boundary polygon |
| Runs | `range(1, 501, 10)`: run_1, run_11, ..., run_491 (50 geometries) |
| Sample | one file per run, `run_NNN.pMean.f32le.bin`, values in VTP polygon order |
| Values per sample | 724,668 - 1,404,826 (median 1,082,412); counts vary with geometry |
| Total | 53,282,167 values, 213,128,668 bytes |

All 500 runs would come to about 2.1 GB of float32, more than the 1 GB cap,
so the recipe takes every 10th run. Downstream sub-samples about 100 MB per
family, so 50 runs are enough.

Only `pMean` is emitted. Excluded:

- `static(p)_coeffMean` is exactly 2 × `pMean` in the probed cells (a linear
  rescale).
- `yPlusMean` is a mesh-resolution diagnostic.
- `wallShearStressMean` is a different, 3-component quantity.
- Excluded geometry and other files: mesh points, connectivity and offsets,
  `boundary_cell_area_<i>.npy` (a geometry helper), `volume_<i>.vtu`
  (~5.6 GB each), `slices/`, `images/`, STL files and force CSVs.

## Decode path

`boundary_<i>.vtp` is VTK XML PolyData with `byte_order='LittleEndian'`,
`header_type='UInt64'`, no compressor, and inline `format='binary'` arrays.
Each array body is one base64 run on a single line. It encodes an 8-byte
UInt64 byte count followed by the raw array bytes, so an array of B bytes
takes `ceil((8 + B) / 3) * 4` characters. `CellData` is the last section of
the `<Piece>` and holds, in order: `pMean`, `static(p)_coeffMean`,
`yPlusMean` (each Float32 ×1) and `wallShearStressMean` (Float32 ×3).

- `discover.sh` resolves where the pMean block sits, using small Range
  requests of about 7 KB per run. It reads `NumberOfPolys` from the first
  2 KB. It finds the end of the last base64 block from the last 1 KB. It then
  walks backwards over the fixed CellData order. At each array it computes
  the block length, fetches 272 bytes around the computed start, and checks
  two things: the opening tag (name, type, component count) and the decoded
  UInt64 prefix. The resulting spans, file sizes, LFS sha256 and xet hashes
  are pinned in `selection.tsv`.
- `download.sh` fetches two Range slices per run:
  - the 2 KB header;
  - the pMean window, which is the base64 block plus 256 bytes before it and
    128 bytes after it.

  Every response must be a 206 with the exact `Content-Range` over the
  pinned file size, a CDN `ETag` equal to the pinned xet hash, and an
  `X-Linked-Etag` equal to the pinned LFS sha256. The window must then pass
  four checks:
  - it starts with `</Polys><CellData><DataArray type='Float32' Name='pMean'
    format='binary'>`;
  - the pinned span is one unbroken base64 run that decodes to exactly
    `8 + 4N` bytes, with UInt64 prefix `4N`;
  - the span is followed by `</DataArray>` and the
    `static(p)_coeffMean` tag;
  - the values are finite, non-constant, within ±10 m^2/s^2, contain both
    suction and stagnation (negative and positive) values, and are distinct
    across runs.
- `build.sh` emits the 4N payload bytes unchanged.
- `verify.sh` re-derives each sample with an offset-free decoder (tag search,
  whitespace strip, decode) and byte-compares it with the stored sample and
  with the offset-based decoder. It recomputes every index field (min/max
  from the stored float32 values, sha256) and checks the manifest totals.

`scripts/ahmedml_vtp.py selftest` runs at every stage. It exercises the walk
and both decoders on synthetic VTP files covering all three base64 padding
residues, plus 10 negative cases: reordered arrays, line-wrapped base64, a
compressor attribute, a wrong prefix, shifted, truncated or mis-sized
windows, NaN, constant and garbage-range fields.

## Files

- `discover.sh`: regenerates `selection.tsv` with small probes only. Its
  scratch output goes to `WORK_DIR`, which defaults to
  `$DATA_DIR/downloads/<id>/discover`.
- `selection.tsv`: the 50 pinned runs with size, hashes, point and polygon
  counts, and pMean base64 span.
- `download.sh`: metadata and license checks, then 100 Range GETs (about
  284.3 MB) into `$DATA_DIR/downloads/ahmedml_cfd_surface_mean_pressure_f32/`.
  It resumes per file and writes logs under `$DATA_DIR/logs/<id>/`.
- `build.sh` and `verify.sh`: local-only decode and independent verification.
- `scripts/ahmedml_vtp.py`: a pure-standard-library helper used by all of
  the above.

## Notes

- Homogeneity: all runs share the solver, turbulence model, inflow, meshing
  pipeline, output variable and units. Only the body geometry varies, and
  with it the polygon count and the pressure distribution.
- The values are full-mantissa float32 as published. OpenFOAM computes in
  double, and float32 is the type of the published VTP arrays.
