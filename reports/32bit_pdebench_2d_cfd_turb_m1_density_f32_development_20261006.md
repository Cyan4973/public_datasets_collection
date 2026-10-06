# PDEBench 2D compressible turbulence density float32 development

## Outcome

Accepted `pdebench_2d_cfd_turb_m1_density_f32`. It holds whole native-float32 mass-density trajectories from the PDEBench 2D compressible Navier-Stokes turbulence training file. Configuration: Mach 1.0, shear and bulk viscosity 1e-8, periodic unit square, 512 × 512 cells, 21 saved steps at t = 0, 0.05, …, 1.0.

This is the first PDE-simulation field family in the local corpus. No downstream counterpart exists. It is the second CFD family at 32 bits in this collection effort, after `ahmedml_cfd_surface_mean_pressure_f32`. That family holds time-averaged surface pressure on an unstructured mesh; this one holds time-resolved, shock-laden density on a dense periodic grid.

The earlier PDEBench attempt, `pdebench_sod6_shock_tube_f64`, was rejected because its small Sod file was degenerate. This recipe uses a different, non-degenerate file. It fetches only the byte ranges it keeps and never requests the 88 GB file.

## Source and rights

- Source: PDEBench Datasets, DaRUS (University of Stuttgart Dataverse), DOI `10.18419/darus-2986`, latest version 8.0 (released 2024-02-13)
- File: DaRUS id 164686, `2D/CFD/2D_Train_Turb/2D_CFD_Turb_M1.0_Eta1e-08_Zeta1e-08_periodic_512_Train.hdf5`
- File size: 88,080,392,528 bytes
- Published MD5: `3f2c7376cde5fb072db0f9814f1c6992`
- S3 ETag: `c094ed9959bb5a60411550403524df31-10000`
- License: CC BY 4.0

The Dataverse record declares `"license": {"name": "CC BY 4.0", "uri": "http://creativecommons.org/licenses/by/4.0"}`. Its terms-of-use, terms-of-access and restriction fields are empty, and the file is not restricted. `download.sh` re-checks the license, the release state and the exact file identity on every run. Citation: Takamoto et al., PDEBench Datasets, DaRUS V8, 2022.

## Shape and conversion

Each natural record is one simulation trajectory, `/density[i]`. Its shape is `(21, 512, 512)` in time-step, x, y row-major order: 5,505,024 values or 22,020,096 bytes.

The HDF5 `/density` dataset is `(1000, 21, 512, 512)` `H5T_IEEE_F32LE`. It is stored contiguously and unfiltered at file address 2048 and is 22,020,096,000 bytes long. A pure-stdlib reader locates it from two SHA-256-pinned 2,048-byte metadata ranges, which allows the trajectory byte ranges to be fetched by HTTP Range and written unchanged.

Selection is fixed at trajectories 0, 25, …, 975, an even stride over the 1000 simulations. Vx, Vy, pressure, the coordinate arrays, the M=0.1 and Rand files, and the 1D/3D files are excluded.

The t = 0 frame is the uniform initial density 1.0 in every trajectory. It is kept as part of the natural record and recorded per sample as `t0_uniform_one`. Any NaN, infinite or non-positive value is fatal in download, build and verify. Nothing is dropped or filled.

## Accepted output

- Source trajectories available: 1,000
- Trajectories collected: 40 (indices 0, 25, …, 975)
- Primary samples: 40
- Primary values: 220,200,960
- Primary bytes: 880,803,840
- Sample size: 5,505,024 values (all samples)
- Downloaded: 881,090,712 bytes = 40 ranges + 4,096 metadata bytes + the 277,219-byte catalog JSON
- Value range: 0.0279–4.835; per-trajectory maxima 3.42–4.83
- t = 0 frame uniform 1.0: 40 of 40
- Distinct values per frame t ≥ 1: at least 258,106 of 262,144
- Aggregate SHA-256: `2af53ee815e601251e263ef10f9e1ce9f12c3a0272628ae4c492a1a0dcc963f1`
- Per-trajectory SHA-256 values: pinned in `trajectory_sha256.tsv`

## Judge checks

- **Gate:** `tools/autocollect/gate.py` PASS with no warnings.
- **verify.sh:** re-run by the judge; verify=ok in 54 s with the aggregate SHA-256 above. The two logged build runs are identical apart from timestamps.
- **build/verify are local-only:** no network calls or imports in build.sh, verify.sh or `verify_density.py`.
- **Negative tests** (scratch symlinked data root): a tampered sample byte, the same edit to both sample and download (caught by the pin), and a tampered index minimum were all rejected.
- **HDF5 layout, parsed independently:** superblock v0 → root TREE → SNOD → local heap. `density` resolves to object header 800, layout v3 contiguous at address 2048, size 22,020,096,000, dataspace `(1000, 21, 512, 512)`, datatype `11201f00…7f` (F32LE), with no filter message. The pressure, Vx and Vy blocks do not overlap it.
- **Bytes** (trajectories 0, 500 and 975, plus all 40 for duplicates):
  - frame means are 1.000000 at every t (mass conservation);
  - lag-1 spatial correlation is 0.993–0.998 on both axes, and the periodic wrap correlation is 0.993–0.999, which confirms the axis order and the periodic boundary;
  - correlation between consecutive saved steps is 0.48–0.69;
  - low-8-mantissa-bit-zero fraction is about 1/256, so the float32 is honest;
  - 801 distinct frames out of 840; the only repeats are the 40 uniform t = 0 frames;
  - cross-trajectory |corr| has median 0.075, and the most correlated pair changes sign over time, so it is not a duplicate;
  - zstd -6 compresses a whole sample 1.22×.
- **Rights:** the fetched catalog and a live re-probe on 2026-10-06 both show CC BY 4.0 with empty terms, and file 164686 is unrestricted. A live 16-byte range request returned 206 with the pinned ETag.
- **Novelty:** `novelty.py` matches only this staging recipe and the rejected `pdebench_sod6_shock_tube_f64` (a different file at 64 bits). There are no downstream matches. The label is new_source rather than new_modality, because AhmedML already covers CFD at 32 bits.
- **The Well MHD-64 precedent:** its "dense Cartesian is not a new layout" argument was secondary to a missing license. It has not blocked later dense-grid 32-bit acceptances (TartanAir optical flow, GWA wind speed, DIODE depth).
- **Caveats** (accepted as-is):
  - Total output is about 881 MB, close to the 1 GB cap. The cap limits whole trajectories to 45.
  - 40 samples is below the soft 50+ guidance.
  - The `t-coordinate` array has 22 entries against 21 density frames. This is documented and does not affect the data.
