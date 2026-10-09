# Hyburn argon decompression near-vent pressure float64 development

## Outcome

Accepted `hyburn_argon_decompression_near_vent_pressure_f64`: native float64 static-pressure fields from the published near-vent 2-D cross-section of a 3-D compressible hydrodynamics simulation. The simulation is Hyburn, built on AMReX, of a pure-argon 1000 psi shock-tube decompression into an expansion chamber.

This is the first CFD or simulated-fluid field family at 64 bits, both locally and in the downstream corpus. The modality already exists at 32 bits (`pdebench_2d_cfd_turb_m1_density_f32`, `the_well_post_neutron_star_merger_density_f32`, `ahmedml_cfd_surface_mean_pressure_f32`), so the novelty kind is `new_content_same_modality`. The candidate also meets the retry condition of the rejected `pdebench_sod6_shock_tube_f64`: a directly downloadable, non-degenerate native-float64 CFD payload under 1 GB. The zlsim breadth measurement is **STRONG**: the nearest family is `sensorless_drive_diagnosis_uci:sdd_feat_042` at distance 0.1324.

## Source and rights

- Source: Zenodo record 4127362, version 1.0.0, DOI 10.5281/zenodo.4127362, published 2020-12-23. von der Linden et al., *Compressible Hydrodynamics Simulation Data for "Standing Shock Prevents Propagation of Sparks in Supersonic Explosive Flows"*.
- Upstream layout: 785 `numpy.savez` archives. There are 394 `tube_*` and 391 `near_vent_*` archives; snapshots 46, 100 and 319 are absent.
- License: CC BY 4.0. It is the record-level `metadata.license.id = "cc-by-4.0"`, so it covers the deposited npz data objects. `download.sh` re-validates the record id, title, description, licence, the near_vent file count, and every archive's size and MD5 on every run.
- No credentials are used. The content is simulated physical fields, with no personal data.

## Shape and conversion

- Natural record: one simulation output snapshot, which is the `pressure.npy` member of one `near_vent_NNNNNN.npz`. Its NPY header is `{'descr': '<f8', 'fortran_order': False, 'shape': (1, 500, 500)}`.
- Access: exact HTTP byte ranges only.
  - For each archive, the 8 KiB tail (central directory and `time.npy`).
  - Then exactly the `pressure.npy` local header and DEFLATE data, at offsets, sizes and CRC32s pinned in `scripts/near_vent_members.tsv`.
  - Full archives (8.38 GB for all near_vent files) are never downloaded.
- Conversion:
  - Inflate the member with raw DEFLATE (`wbits=-15`). Require the CRC32 and size to match the local header and the pinned table.
  - Parse the NPY v1 header and write the 2,000,000-byte payload verbatim after it.
  - There is no cast, rescale or reorder, and nothing else is emitted.
- Selection:
  - Even snapshot numbers only.
  - Keep a snapshot only if its ambient fraction (cells within 1 Pa of 101325 Pa) is at most 0.5 and no single float64 value covers more than half the cells. Pre-jet frames are ambient air carrying about 1e-8 Pa of round-off noise, which a dominant-value test alone would not catch.
  - Snapshot 28 has an ambient fraction of 0.543 and snapshot 30 has 0.465, so the kept range starts at 30.
- Excluded: the `tube_*` window and the other 32 members (density, velocities, temperature, schlieren, Mach number, all-zero particle fields, mesh, time and load-balance cost).

## Accepted output

- Series: `near_vent_pressure_pa_f64`, primary, native_numeric, float64 little-endian.
- Primary samples: 180, every existing even snapshot from 30 to 392.
- Values per sample: 250,000 (500 x 500), so 2,000,000 bytes per sample.
- Primary values: 45,000,000.
- Primary bytes: 360,000,000.
- Pressure range: 1,309.651707431094 Pa to 866,938.2744165752 Pa.
- Simulation time: 0.427 ms (snapshot 30) to 6.677 ms (snapshot 392). The median spacing between outputs is about 17.3 µs, so kept frames are about 35 µs apart.
- Maximum ambient fraction: 0.465 (snapshot 30); all other samples are below 0.01.
- Maximum dominant-value fraction: 0.0717.
- Mean uniform-2x2-block fraction: 0.0042.
- Distinct values per sample: 123,535 to 212,862.
- All 180 SHA-256 hashes are distinct.
- Aggregate SHA-256 of the samples concatenated in index order: `ad9a2e45713a89c79eb187cbe5d428c907a71ccf0cc0a3b297dcf3e73dc5288b`.
- Download: 244,965,509 range bytes for the 180 snapshots.

Known caveats, disclosed in the README and manifest:

- All samples come from a single simulation run.
- Kept frames are temporally correlated.
- The data is the authors' post-processed uniform slice, not the raw AMReX plotfiles. Where the slice crosses coarser AMR levels, a fixed set of rows repeats values. This is native to the product and modest.
- The README and manifest say outputs are "~15 µs" apart. The measured median is 17.3 µs (range 11–19 µs), so the figure is imprecise but not material.

## Judge checks

- `python3 tools/autocollect/gate.py staging/hyburn_argon_decompression_near_vent_pressure_f64`: PASS, no warnings. 180 samples, 45,000,000 values, 360,000,000 bytes, median 250,000 values per sample.
- `bash staging/.../verify.sh` (run by me): `verify ok samples=180 total_bytes=360000000`. It independently re-inflates each member and byte-compares it with the sample.
- `build.sh` reads only `.data/downloads/<id>/` members.
- Bytes, checked with stdlib `struct` on snapshots 30, 56, 80, 202, 274 and 392:
  - Mantissa trailing-zero counts fall off geometrically, so the data is genuine float64 with no float32 widening.
  - Adjacent kept frames have 0 identical cells and about 2.6% median relative change, so they are not near-duplicates.
  - An ASCII log-pressure map shows the nozzle jet, expansion cell, Mach disk and chamber.
  - The chamber's p25–p75 is about 97–105 kPa, and nothing is dominated by a fill value.
- Selection table: 391 rows, 180 selected. Every existing even snapshot from 30 to 392 is selected, and the fractions of snapshots 24–34 confirm the documented cut-off.
- Rights: I fetched `https://zenodo.org/api/records/4127362` myself. It reports `license.id = cc-by-4.0`, access open, version 1.0.0 and 785 files. A grep of the recipe found no credentials.
- Novelty, from `novelty.py` URL, terms and breadth-key queries plus the downstream 64-bit listings:
  - No prior use of the source.
  - There are 32-bit sim_fluid_field members, but no 64-bit CFD or simulated-fluid field anywhere.
  - zlsim measured STRONG, with nearest distance 0.1324.
