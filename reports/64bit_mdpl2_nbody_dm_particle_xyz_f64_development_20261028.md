# MDPL2 N-body dark-matter particle positions float64 development

## Outcome

Accepted `mdpl2_nbody_dm_particle_xyz_f64` from Zenodo record 5259075 (version 1.0). The record holds the 72-million-particle downsample of the a = 0.7333 (z = 0.36) snapshot of the MultiDark-Planck 2 (MDPL2) N-body simulation, a periodic 1000 Mpc/h box.

This is the corpus's first cosmological-simulation particle material at any width. `novelty.py` found no URL, term or breadth-key match locally or downstream. The nearest families are:

- the 64-bit xyz point sets `megascenes_colmap_sfm_point_xyz_f64` and `orex_ola_l2_lidar_point_xyz_f64`;
- the molecular-dynamics coordinates `figshare_rmd17_trajectories_f64`;
- the few-body Solar System integration `zenodo_janus_solar_system_integer_phase_space_i64`.

The measured breadth verdict is OK (nearest feature distance 0.1045).

Acceptance came after one repair cycle, which changed only text and statistics:

- The first draft described the prefix as one contiguous region in a single space-filling order. It covers two disjoint regions, and the manifest, README and stats now say so.
- Build and verify now record and enforce the float32-print property that the float64 width ruling rests on.
- A README novelty overclaim and a stale status section were corrected, and the license notes now cover the CosmoSim terms of use.

## Source and rights

- Source: Zenodo record 5259075, file `mdpl2_particles_0.7333_72m.npy`, 1,723,358,504 bytes, Zenodo MD5 `fdebca8efbac362f57de94c342537b8d`. It is an NPY v1 structured array of 71,806,599 records `[('x','<f8'),('y','<f8'),('z','<f8')]`.
- Fetched: one HTTP range, bytes 0-384,000,127, which covers the 128-byte header and the first 16,000,000 records.
- Pins: exact header, prefix SHA-256 `fa5904abedb4020bfc14276a7ee191db98478a253aa27a10d80c99b6ad50c89a`, plus the record's license, size and MD5, re-checked on every run.
- License: CC BY 4.0, declared in the record metadata. The record description adds no restriction.
- Upstream: the CosmoSim / MultiDark Database credits page welcomes use of the simulation data "for your own scientific purposes without further consultation" and asks for acknowledgement and citations. Its terms of use govern registered accounts and query storage, not the data. The recipe uses no CosmoSim account or service.
- Caveat: the database publishes no formal data license, so the grant rests on the Zenodo record's CC BY 4.0.
- Attribution: the Zenodo authors (Huang et al. 2021), the MDPL2 simulation paper (Klypin et al. 2016) and the MultiDark Database paper (Riebe et al. 2013).

## Shape and conversion

- **Natural record.** The whole catalog is one natural record: the downsampled particle set of one snapshot. It exceeds the 1 GB cap, so the recipe keeps the first 16,000,000 records in file order (22.3%) as one sample and does not tile it.
- **Conversion.** The 384,000,000 bytes after the NPY header are written verbatim as little-endian float64, x0, y0, z0, x1, and so on.
- **Value checks.** Every value must be finite, inside [0, 1000] Mpc/h, a number with at most six decimals, and the six-decimal print of its nearest float32.
- **Width.** The positions are single-precision values published as float64 through six-decimal text.
  - All 48,000,000 values equal the six-decimal print of their nearest float32, and only 152,254 (0.317%) are float32-exact.
  - The effective lattice is the float32 step: 3.05e-5 Mpc/h in [256, 512) and 6.1e-5 above 512.
  - float64 is kept because it is the publisher's stored dtype; narrowing would rewrite 99.68% of the stored bit patterns.
- **Spatial order.** In catalog order every touched 1.95 Mpc/h and 62.5 Mpc/h cell is one contiguous run, and the median 3-D step is 1.38 Mpc/h.
  - The prefix covers two disjoint regions of 62.5 Mpc/h cells: 815 cells with 14,298,713 particles (x 500-1000, z 500-1000 Mpc/h) and 98 cells with 1,701,287 particles (x 0-500, y 0-500, z 0-250 Mpc/h).
  - The order moves between them 77 times.
- **Not used.** The halo catalog and the cluster and lensing files in the same record.

## Accepted output

- Primary samples: 1
- Primary values: 48,000,000 (16,000,000 particles × 3)
- Primary bytes: 384,000,000
- Value range: 0.0 to 999.999939 Mpc/h; 0 non-finite
- Per-axis means: x 707.68, y 455.07, z 678.18 Mpc/h
- Decimal places: 43,211,583 values with six, 4,280,328 with five
- float32-print values: 48,000,000; float32-exact values: 152,254
- Cells and runs in file order: 250 Mpc/h 17 / 94; 62.5 Mpc/h 913 / 913; 1.95 Mpc/h 7,753,972 / 7,753,972
- Complete 15.6 Mpc/h cells: 29 to 2,855 particles (median 228)
- Consecutive repeated positions: 0
- Sample SHA-256: `9f12e09b3e801998e41bafe46c7cc249f3ae57de23fba15cd54037541a28852f`

## Judge checks

- **Mechanics.** `tools/autocollect/gate.py` passed with no warnings, before and after the repair: 1 sample, 48,000,000 values, width 64.
- **Reproducibility.**
  - `verify.sh` passed on both passes. The sample is byte-identical to the pinned prefix records, and the stats and index recompute equal.
  - The current validator passed with the SHA pin enforced.
  - Three 64 KiB ranges fetched from the Zenodo content URL (offsets 0, 200,000,000 and 383,934,592) matched the local prefix byte for byte.
  - build and verify use only local files, and no script contains credentials.
- **Bytes.** I read all 48,000,000 values with stdlib `struct`/`memoryview`.
  - Range, finiteness and per-cell density match the 1000 Mpc/h box and the 71.8M-particle catalog (median 17,356 particles per 62.5 Mpc/h cell, against 17,531 expected).
  - 0 exact duplicate positions in three 4M-particle blocks.
- **Width.** I independently confirmed the float32-print property on every value (0 failures) and the 152,254 float32-exact count. Low-byte entropy is 7.74 bits and mantissa trailing zeros fall off geometrically, so nothing is zero-padded.
  - Ruling: float64 is honest. It is the publisher's stored binary dtype, the recipe does no widening, and the provenance is disclosed and enforced. This is the same basis on which kollmeyer and dandi_ibl publisher-stored doubles were accepted.
- **Spatial claims.** I computed face-connected components and region switches myself. My results equal the recorded stats (regions 815 / 98 cells, 14,298,713 / 1,701,287 particles, 77 switches; 17 cells in 94 runs at 250 Mpc/h).
- **Rights.** I opened the local and live Zenodo record JSON, the CosmoSim credits page and its terms of use. CC BY 4.0 covers the exact file, and no upstream text restricts derived data.
- **Novelty and breadth.**
  - `novelty.py` URL, term and breadth-key queries found no match.
  - The zlsim neighbours that are compression-equivalent (Binance volume f64, loss -0.04) are decimal-origin doubles at feature distance above 0.10, so they are not redundant.
- **Volume and shape.** One 384 MB sample from a one-record source. The download is about equal to the output, and the sample is large enough for downstream to shard.
- **Known nit, fixed at promotion.** `missing_value_policy` did not list the float32-print failure condition that `deterministic_notes`, `representation_notes` and the README already stated. It now does; this is a manifest text change only, and `verify.sh` passed again after the recipe moved to `datasets/`.
