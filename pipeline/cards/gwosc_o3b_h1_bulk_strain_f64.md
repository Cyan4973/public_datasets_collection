# GWOSC O3b Bulk LIGO Hanford (H1) Calibrated Strain h(t), 4 kHz, 4096-s Archive Files (DCS-CALIB_STRAIN_CLEAN_SUB60HZ_C01), Native Float64

- Candidate id: `gwosc_o3b_h1_bulk_strain_f64`
- Width: float64
- Quantity: Dimensionless calibrated, cleaned gravitational-wave detector strain h(t) of LIGO Hanford during observing run O3b (Nov 2019 - Mar 2020), downsampled by GWOSC to 4096 Hz. The values are about 1e-19 to 1e-21 colored detector noise (seismic, thermal and shot-noise spectrum with lines).
- Source: https://gwosc.org/archive/O3b/
- Resources: https://gwosc.org/api/v2/runs/O3b/strain-files?detector=H1&format=json, https://gwosc.org/archive/data/O3b_4KHZ_R1/1259339776/H-H1_GWOSC_O3b_4KHZ_R1-1260003328-4096.hdf5, https://gwosc.org/timeline/segments/json/O3b_4KHZ_R1/H1_DATA/1256655618/1269363618/, https://doi.org/10.7935/pr1e-j706
- License: CC BY 4.0
- License evidence: https://gwosc.org/archive/O3b/
- License quote: Data released under a CC BY 4.0 License (footer of gwosc.org/archive/O3b/, gwosc.org/data/ and gwosc.org/acknowledge/, linking https://creativecommons.org/licenses/by/4.0/)
- Natural record: One GWOSC bulk archive file: the strain/Strain dataset of one 4096-s H1 4 kHz O3b HDF5 file, 16,777,216 float64 values (134 MB). Only files fully inside H1_DATA segments are used, so they contain no NaN.
- Estimated samples: 7
- Estimated primary values: 117,440,512
- Estimated download bytes: 910,000,000
- Estimated primary bytes: 939,524,096
- Decode path: The GWOSC API v2 /runs/O3b/strain-files?detector=H1 lists 4096-s files with hdf5 URLs (the 4 kHz H1 subset has about 2,686 files). The timeline segments JSON (H1_DATA) selects files fully covered by science data. Choose 6-7 spread evenly over O3b and pin name, size and sha256. download.sh uses curl -C - with speed-limit, about 129 MB per file (gzip chunks barely compress real noise). Stdlib HDF5 reader (the repo already has several h5lite-style readers used by hutubs, SOFA and NOAA recipes): superblock v0, group B-tree to /strain/Strain, chunked layout with deflate filter, zlib.decompress each chunk, dtype <f8. Reject files with any NaN or all-zero chunks. Verified: mid-run chunks inflate to 65,536 bytes (8,192 doubles) with values around ±8e-19, 4096/4096 distinct, 0 float32-exact.
- Novelty kind: new_content_same_modality
- Measurement type: gw_detector_strain
- Instrument line: ligo_hanford_h1_o3b
- Archive collection: gwosc.org/archive/O3b_4KHZ_R1
- Novelty evidence: novelty.py: no 64-bit GW strain anywhere, local or downstream. The only gw_detector_strain family is gwosc_event_strain_f32, which parses the GW150914 32-s TEXT event files into float32 (a lossy narrowing), and downstream gwosc_strain_f32 is 32-bit. This candidate uses a different product line (O3b bulk run archive, HDF5, native float64 at the honest source width) and different content (5 months of run data, not the 2015 event window). sxs_bbh_extrapolated_strain_modes_f64 is simulated waveform modes (smooth chirps), a different generation process. No registry or ledger hits for gwosc/O3b bulk; gwtc3 posterior samples (staged) are PE samples, not strain.
- Homogeneity: One detector (H1), one run (O3b), one calibration and cleaning version (C01 CLEAN_SUB60HZ), one sample rate (4 kHz), one quantity and unit. Do not mix L1 or V1 (different noise spectra) or the 16 kHz release. Only full-science-mode files, with no NaN gaps.
- Risks: (1) Low sample count (6-7) is forced by the 1 GB cap with 134 MB natural records. A judge may prefer more records. The alternative is the GWTC-2.1/3 'confident' event 32-s 4 kHz HDF5 files (live, ~1.03 MB each, about 89 O3 events x H1/L1 ≈ 150 samples, ~157 MB), but that reuses the event-file product line of the f32 baseline and is closer to a width mirror. (2) Byte-gate: strain is colored noise dominated by low frequencies. The rejected DANDI iEEG matched grail_lgrs_kbr1c range-acceleration at distance 0.034, so zlsim may also find GW strain equivalent to a smooth f64 family. Its ~1e-20 scale and line structure may differ, but this is unverified. (3) The gwosc.org HTML archive pages are JS-heavy; use the JSON API.
- Probe evidence: 2026-10-09: /api/v2/runs lists O3b (gps 1256655618-1269363618, DOI 10.7935/pr1e-j706). /api/v2/runs/O3b/strain-files?detector=H1 has 5,372 results (4 and 16 kHz). HEAD of H-H1_GWOSC_O3b_4KHZ_R1-1260003328-4096.hdf5 returned 200 with Content-Length 129,477,462. A 200 KB head range shows the HDF5 signature and channel H1:DCS-CALIB_STRAIN_CLEAN_SUB60HZ_C01. A 400 KB mid-file range inflated three deflate chunks to genuine float64 strain. The first O3b file (1256660992) starts with NaN chunks (pre-lock), which confirms the need for H1_DATA segment selection; the segments JSON endpoint is live. The CC BY 4.0 footer is present on /data/, /acknowledge/ and /archive/O3b/.

Proposed by the autocollect scout on 2026-10-09 (transcript `.data/pipeline/logs/scout_64bit/scout.20261009_114544.jsonl`).
