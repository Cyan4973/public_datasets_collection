# Hybrid-Kinetic 3-D Perpendicular-Shock / Pre-Existing-Turbulence Simulation (Trotta et al. 2023): 256^3 Magnetic-Field Component Grids, Native Float64

- Candidate id: `trotta_hybrid_shock_turbulence_bfield_f64`
- Width: float64
- Quantity: Magnetic-field Cartesian components B_x, B_y, B_z (normalized to upstream B0) on a 256^3 grid (0.5 d_i resolution) from a hybrid-kinetic (kinetic ions, fluid electrons) simulation of a perpendicular collisionless shock interacting with upstream turbulence of level dB/B
- Source: https://zenodo.org/records/7964045
- Resources: https://zenodo.org/api/records/7964045/files/dB05_B_x-16.txt/content, https://zenodo.org/api/records/7964045/files/dB10_B_z-16.txt/content
- License: CC-BY-4.0
- License evidence: https://zenodo.org/records/7964045
- License quote: Zenodo record 'Three-dimensional modelling of shock-turbulence interaction. Magnetic field and temperature datasets': license id 'cc-by-4.0' (Creative Commons Attribution 4.0 International). Description: 'These textfiles are stored as one-dimensional array, which need to be reshaped to a 256x256x256 grid (which has a resolution of 0.5 di).'
- Natural record: One field snapshot = one text file <level>_B_<comp>-<time>.txt holding 16,777,216 values (256^3) written with numpy '%.18e' (exact f64 round-trip)
- Estimated samples: 6
- Estimated primary values: 100,663,296
- Estimated download bytes: 2,567,000,000
- Estimated primary bytes: 805,306,368
- Decode path: Stream each text file line by line with float() (the %.18e repr round-trips exactly to the stored double) and pack '<d'. Check exactly 16,777,216 lines per file. Suggested scope, bounded by the 1 GB cap: B_x, B_y and B_z at TΩci=16 for the two turbulent cases dB05 and dB10, giving 6 samples = 805 MB. Alternative: the 6 B_z files across all levels and both times.
- Novelty kind: new_modality
- Measurement type: sim_plasma_field
- Instrument line: hybrid_kinetic_pic_camelia_shock
- Archive collection: zenodo
- Novelty evidence: novelty.py --url https://zenodo.org/records/7964045 --terms hybrid-kinetic shock turbulence Trotta: no URL match. Term hits are unrelated: shock audio/plasma-wave recordings at 8/16 bit, pdebench CFD. The vocabulary has no simulated space-plasma or kinetic-plasma field type at any width. The nearest types are sim_fluid_field (32-bit only) and measured orbital_magnetometer / interplanetary_magnetic_field (smooth time series, not 3-D noisy kinetic grids).
- Homogeneity: One code and run family, one quantity (B components, same normalization), one grid (256^3), one output format. Exclude B_mag (non-negative, different distribution) and Tpar/Tperp (different unit). The turbulence level (0.5 vs 1.0) is a physical parameter of the same regime, not a unit or scale change.
- Risks: (1) Only 6 samples (the 1 GB cap with 134 MB per natural record), at the soft minimum. (2) Heavy extraction ratio: about 2.57 GB of %.18e text for 805 MB kept. (3) Each sample is a 3-D grid flattened in the authors' 1-D order, kept as published. (4) Hybrid-PIC noise gives full-mantissa values, likely distinct from smooth f64 series, but zlsim may still pair it with another noisy f64 family. (5) Some B_x/B_y files are slightly larger than 256^3*25 bytes (sign characters), so do not assume fixed-width lines.
- Probe evidence: Zenodo API lists 30 files: dB00, dB05 and dB10, each with B_mag/B_x/B_y/B_z at -14 and -16 plus Tpar/Tperp at -14; sizes 419.4-427.9 MB (419,430,400 = 256^3 x 25 bytes). Range GET 0-299 of dB00_B_x-14.txt: lines such as '6.076501410963124419e-03', '-1.242681160364478288e-02' (19 significant digits, numpy %.18e). dB00_Tpar-14.txt starts '4.355821133155868274e-01'.

Proposed by the autocollect scout on 2026-10-09 (transcript `.data/pipeline/logs/scout_64bit/scout.20261009_102323.jsonl`).
