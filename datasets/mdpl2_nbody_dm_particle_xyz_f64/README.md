# MDPL2 N-Body Dark-Matter Particle Positions Float64

Native float64 comoving positions of dark-matter particles from MultiDark-Planck 2 (MDPL2),
a 3840^3-particle N-body simulation of a periodic 1000 Mpc/h box with Planck cosmology. The
source is the 72-million-particle downsample of the a = 0.7333 snapshot (z = 0.36) that Huang
et al. published on Zenodo (record 5259075, CC-BY-4.0) with their paper on the outer stellar
mass of massive galaxies. The recipe keeps the first 16,000,000 particles in catalog order:
one sample of 48,000,000 values (x0, y0, z0, x1, ...), 384,000,000 bytes.

## Why this material

The corpus has no cosmological-simulation particle data at any width, locally or downstream.
Its nearest families are the 64-bit xyz point sets `megascenes_colmap_sfm_point_xyz_f64` and
`orex_ola_l2_lidar_point_xyz_f64`, the molecular-dynamics coordinates
`figshare_rmd17_trajectories_f64`, and the few-body JANUS Solar System integration
`zenodo_janus_solar_system_integer_phase_space_i64`.

Measured on the built sample (16,000,000 particles):

- In catalog order, every touched cell of a 62.5 Mpc/h grid (913 cells) and of a
  1.95 Mpc/h grid (7,753,972 cells) is one contiguous run of records, so most consecutive
  particles are close: the median 3-D step is 1.38 Mpc/h. The prefix is not one region,
  though. Its 62.5 Mpc/h cells form two disjoint regions, 815 cells holding 14,298,713
  particles and 98 cells holding 1,701,287, and the order moves between them 77 times.
  Dark-matter clustering makes the density uneven: complete 15.6 Mpc/h cells hold 29 to
  2,855 particles (median 228).
- The positions are single-precision values published as float64 through six-decimal
  text: every value equals the six-decimal print of its nearest float32. Their effective
  lattice is therefore the float32 step (3.05e-5 Mpc/h between 256 and 512 Mpc/h, 6.1e-5
  above); only below about 16 Mpc/h is the 1e-6 decimal grid the coarser one. 90% of the
  values have exactly six decimals, but only 0.32% are exactly representable in float32.
  Between 600 and 601 Mpc/h the sample holds 16,160 distinct values, against 16,384
  float32 steps and 1,000,000 six-decimal steps in that interval. float64 is kept because
  it is the publisher's stored dtype; narrowing to float32 would rewrite 99.68% of the
  stored bit patterns.
- There are no fill values, and no particle repeats the position of the previous one.

## Provenance and license

- Zenodo record 5259075 (version 1.0, 2021-09-01, the latest of two versions) declares
  CC-BY-4.0, and its description adds no restriction. `download.sh` re-checks the license
  and the particle file's listed size and MD5 on every run.
- The particles come from MDPL2 (Klypin et al. 2016, MNRAS 457, 4340), distributed by the
  CosmoSim / MultiDark Database at AIP. Its credits page welcomes use of the simulation data
  "for your own scientific purposes without further consultation" and asks for an
  acknowledgement and citations. It states an intent and asks for credit; it adds no
  restriction. The CosmoSim terms of use govern registered accounts and query storage, not
  the data, and this recipe uses no CosmoSim account or service. The MultiDark Database
  publishes no formal data license, so the grant rests on the Zenodo record's CC-BY-4.0.

## Selection

The full particle file is 1,723,358,504 bytes, above the 1 GB cap. `download.sh` fetches
one HTTP byte range: the 128-byte NPY header and the first 16,000,000 of 71,806,599 records
(22.3%, 384,000,128 bytes); it covers the two regions described above. The whole catalog is
one natural record, the downsampled particle set of one snapshot, so the recipe emits a
single sample and does not tile it. The halo catalog in
the same record (54.8 MB, mixed per-halo properties) is a different material and is not
used.

## Scripts

- `download.sh`: saves the Zenodo record metadata, fetches the prefix with resumable range
  requests, and runs `scripts/mdpl2_particles.py validate`.
- `build.sh`: checks the record, the exact NPY header, the prefix size and SHA-256 and every
  value (finite, inside [0, 1000] Mpc/h, at most six decimals, the six-decimal print of a
  float32), then writes the records verbatim.
- `verify.sh`: re-reads the prefix, compares the sample byte for byte, and recomputes the
  statistics and the index row.

## Status

Downloaded, built and verified locally on 2026-10-28: 1 sample, 48,000,000 values,
384,000,000 bytes, sample SHA-256
`9f12e09b3e801998e41bafe46c7cc249f3ae57de23fba15cd54037541a28852f`.
