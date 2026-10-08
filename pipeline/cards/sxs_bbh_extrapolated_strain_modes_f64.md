# SXS Binary-Black-Hole Simulation Catalog: Extrapolated Asymptotic Strain Spherical-Harmonic Modes rh/M (Extrapolated_N2, CoM-corrected), Float64

- Candidate id: `sxs_bbh_extrapolated_strain_modes_f64`
- Width: float64
- Quantity: Complex gravitational-wave strain modes r·h_lm/M (real and imaginary parts, dimensionless) from SpEC numerical-relativity binary black hole mergers. The data are native float64 HDF5 datasets [N,3] of (t/M, Re, Im).
- Source: https://zenodo.org/communities/sxs
- Resources: https://zenodo.org/api/records?communities=sxs&size=2, https://zenodo.org/api/records/3301877, https://zenodo.org/api/records/3301877/files/SXS:BBH:0305/Lev6/rhOverM_Asymptotic_GeometricUnits_CoM.h5/content
- License: CC BY 4.0, declared per Zenodo record (license id 'cc-by-4.0' on each SXS:BBH simulation record)
- License evidence: https://zenodo.org/api/records/3301877
- License quote: Zenodo record 3301877 'Binary black-hole simulation SXS:BBH:0305' metadata: "license": {"id": "cc-by-4.0"}
- Natural record: One HDF5 dataset Extrapolated_N2.dir/Y_l{l}_m{m}.dat in one simulation's highest-resolution rhOverM_Asymptotic_GeometricUnits_CoM.h5. Primary is interleaved Re/Im (N x 2); the time column is auxiliary, shared across a simulation's modes. Take only the N2 extrapolation order: N3/N4/Outermost are near-duplicates.
- Estimated samples: 1,155
- Estimated primary values: 30,000,000
- Estimated download bytes: 1,160,000,000
- Estimated primary bytes: 240,000,000
- Decode path: curl the full CoM .h5 (about 77 MB per simulation) for about 15 pinned SXS:BBH records via Zenodo /files/<key>/content URLs, with checksums from the record API. The HDF5 is superblock v0 (h5py/scri.SpEC), with chunked datasets using shuffle+deflate filters. A pure-Python HDF5 reader is needed: symbol-table groups, v1 chunk B-tree, then zlib inflate and byte unshuffle. The repo has HDF5-parsing precedent (zenodo_lodopab probe_hdf5.py, dandi, goes builds). Self-test on a synthetic file.
- Novelty kind: new_modality
- Measurement type: sim_gravitational_waveform
- Instrument line: spec_numerical_relativity_bbh
- Archive collection: zenodo.org/communities/sxs
- Novelty evidence: novelty.py --url https://zenodo.org/records/3301877 --terms SXS 'numerical relativity' rhOverM black-hole: same host only (zenodo, many recipes). No SXS, numerical-relativity or waveform-mode recipe, registry, ledger or downstream entry exists; the only 'black-hole' hit is the_well post-merger density (f32 3-D fluid field). gw_detector_strain (GWOSC f32) is noise-dominated detector data at another width. Smooth, deterministic chirp-and-ringdown complex modes in f64 are a new modality at 64-bit.
- Homogeneity: One code (SpEC), one waveform product (rhOverM asymptotic, extrapolation order N2, center-of-mass corrected) and one unit (dimensionless rh/M). Mode amplitudes differ strongly by l (l=2 about 0.1, l=8 about 1e-6). If the judge objects, restrict to l<=4 (21 modes per simulation) and take more simulations. Pin simulations of one catalog vintage (2019 Zenodo deposits).
- Risks: Zenodo host: this effort already has at least 2 Zenodo acceptances, so a third may wait for user sign-off. The HDF5 chunk/filter decode is real tooling work; if it fails, record needs_tooling. Each 77 MB file keeps only the N2 group, about a quarter of the file (more if uncompressed-size dominated), unless the builder range-reads only the needed chunks. Late-time and high-l modes contain numerical junk/noise; that is genuine material but worth noting. Newer CaltechDATA catalog versions use a compressed RPDMB representation; use the 2019 Zenodo deposits instead.
- Probe evidence: Zenodo API community=sxs total 2196 records. Record 3301877 (SXS:BBH:0305, published 2019-07-10, license cc-by-4.0) lists Lev1-Lev6 files incl. Lev6/rhOverM_Asymptotic_GeometricUnits_CoM.h5 = 76,649,191 B. A 4 KB range read shows the HDF5 v0 superblock (\x89HDF, version 0). A 64 KB range read shows scri.SpEC metadata 'rhOverM_Asymptotic_GeometricUnits.h5/Extrapolated_N2.dir' plus 'shuffle' and 'deflate' filter names. Range GET -r 0-0 returned 206.

Proposed by the autocollect scout on 2026-10-08 (transcript `.data/pipeline/logs/scout_64bit/scout.20261008_162656.jsonl`).
