# Hyburn/AMReX 3-D Compressible Argon Decompression (Shock-Tube Vent) Simulation: Near-Vent 2-D Cross-Section Pressure Fields, 391 Snapshots, Native Float64

- Candidate id: `hyburn_argon_decompression_near_vent_pressure_f64`
- Width: float64
- Quantity: Gas pressure (Pa) on a 500x500 2-D cross-section of a 3-D compressible hydrodynamics simulation (Hyburn, AMReX) of a 1000 psi pure-argon decompression into an expansion chamber, near-vent window
- Source: https://zenodo.org/records/4127362
- Resources: https://zenodo.org/api/records/4127362/files/near_vent_000200.npz/content, https://zenodo.org/api/records/4127362/files/near_vent_000000.npz/content
- License: CC-BY-4.0
- License evidence: https://zenodo.org/records/4127362
- License quote: Zenodo record 'Compressible Hydrodynamics Simulation Data for "Standing Shock Prevents Propagation of Sparks in Supersonic Explosive Flows"': license id 'cc-by-4.0' (Creative Commons Attribution 4.0 International). Description: 'This data is a 2D cross-section from a 3D compressible hydrodynamics simulation (Hyburn / AMRex code) of a rapid decompression / shock tube experiment...'
- Natural record: One simulation output time = one near_vent_NNNNNN.npz; the primary is its pressure.npy member: float64, shape (1,500,500) = 250,000 values
- Estimated samples: 391
- Estimated primary values: 97,750,000
- Estimated download bytes: 520,000,000
- Estimated primary bytes: 782,000,000
- Decode path: download.sh: for each near_vent_NNNNNN.npz, range-GET the last 8 KB (central directory, 33 members), parse with struct to find pressure.npy local-header offset and compressed size, then curl -r just that member (deflate, about 1.4 MB at mid-run). This avoids the about 23 MB full npz. build: zlib.decompressobj(-15), parse the NPY v1 header ('<f8', fortran_order False, shape (1,500,500)), and write 250,000 LE f64. Optionally fetch time.npy (88 B) as auxiliary. Verify the stored CRC32 from the central directory.
- Novelty kind: new_source
- Measurement type: sim_fluid_field
- Instrument line: hyburn_amrex_compressible_multiphase
- Archive collection: zenodo
- Novelty evidence: novelty.py --url https://zenodo.org/records/4127362 --terms Hyburn decompression shock near_vent: no URL match. The only related hit is staging pdebench_sod6_shock_tube_f64, REJECTED for degeneracy with retry_condition 'Retry only with a directly downloadable non-degenerate native-float64 CFD payload whose complete primary output stays below 1 GB'. This candidate meets that condition. sim_fluid_field has only 32-bit members (ahmedml, pdebench 2D turb, the_well); there is no 64-bit simulated fluid field.
- Homogeneity: One field (pressure, Pa), one simulation run, one window (near-vent), one grid (500x500), all 391 snapshots. The tube window (394 snapshots, a different region with large uniform interior) and the other 30 fields are deliberately excluded.
- Risks: (1) Values repeat in 2x2 blocks (each top value appears 4 times), which looks like upsampling of coarse AMR levels to the uniform 500x500 slice. That is native to the published product, but it lowers entropy. (2) The earliest frames (near_vent_000000 npz is only 694 KB total) are mostly ambient, so verify must flag samples dominated by one value. The builder may start the range after the jet has developed, or justify keeping all frames. (3) Consecutive snapshots are temporally correlated. (4) This is a published post-processed slice of the AMReX plotfiles, not raw plotfiles. (5) There are 391 per-file range requests, so the download is slow but bounded.
- Probe evidence: Zenodo API: 785 npz files (394 tube_*, 391 near_vent_*). Central directories range-fetched for tube_000200, tube_000010 and near_vent_000200 list 33 members (pressure, density_gas, xVel_gas, ..., time.npy), each 2,000,080 bytes uncompressed; near-vent pressure csize 1,385,017. NPY header: {'descr': '<f8', 'fortran_order': False, 'shape': (1, 500, 500)}. A partial inflate (first 200 KB compressed, about 37k values) of near_vent_000200 and near_vent_000050 pressure gave 31,840 and 32,135 distinct values, min 12,152 / 24,827 Pa, max 517,631 / 791,374 Pa, ambient about 1e5 Pa: not degenerate, full mantissa.

Proposed by the autocollect scout on 2026-10-09 (transcript `.data/pipeline/logs/scout_64bit/scout.20261009_102323.jsonl`).
