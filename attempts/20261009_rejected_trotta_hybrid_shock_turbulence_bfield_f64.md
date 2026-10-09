# trotta_hybrid_shock_turbulence_bfield_f64

- Date: 2026-10-09
- Status: rejected
- Candidate dataset: Hybrid-Kinetic 3-D Perpendicular-Shock / Pre-Existing-Turbulence Simulation (Trotta et al. 2023): 256^3 Magnetic-Field Component Grids, Native Float64
- Source: https://zenodo.org/records/7964045
- Why it looked promising: see `pipeline/cards/trotta_hybrid_shock_turbulence_bfield_f64.md`
- Failure class: autocollect driver limit
- What happened: byte-level breadth: every primary series is compression- and feature-equivalent to an existing family: trotta_shock_turbulence_bfield_component_f64 ~ local:nasa_pds_gravity_harmonics_f64:gravity_cosine_cnm_f64 (distance 0.0317, loss +0.001)
- Evidence:
  - 2026-10-09T10:40:50 proposed: {"log": ".data/pipeline/logs/scout_64bit/scout.20261009_102323.jsonl"}
  - 2026-10-09T10:45:34 screened: {"decision": "approve", "reason": "Simulated kinetic-plasma 3-D B-field grids are new; novelty.py shows no hits. Zenodo confirms CC-BY-4.0 and 30 text files, and a range GET returns 206. %.18e text round-trips exactly to f64, so the f64 width is honest. One code, one quantity and one normalization.
  - 2026-10-09T11:06:01 builder: {"phase": "author", "status": "ready_for_download", "log": ".data/pipeline/logs/trotta_hybrid_shock_turbulence_bfield_f64/builder.20261009_105937.jsonl", "cost": 1.4618978000000002}
  - 2026-10-09T13:54:01 download: {"rc": 0, "reason": "", "bytes": 2550277436, "log": ".data/pipeline/logs/trotta_hybrid_shock_turbulence_bfield_f64/download.20261009_123828.log"}
  - 2026-10-09T13:58:04 builder: {"phase": "build", "status": "ready_for_judge", "log": ".data/pipeline/logs/trotta_hybrid_shock_turbulence_bfield_f64/builder.20261009_135402.jsonl", "cost": 0.24121940000000003}
  - 2026-10-09T14:31:19 rebuild: {"ok": true}
- Logs: `.data/pipeline/logs/trotta_hybrid_shock_turbulence_bfield_f64/`, `.data/logs/trotta_hybrid_shock_turbulence_bfield_f64/`
- Decision: rejected
- Retry conditions: Retry only with material whose bytes differ measurably (zlsim.py gate) from the existing families.
