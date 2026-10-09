# dandi_000488_openscope_2p_dff_traces_f64

- Date: 2026-10-09
- Status: rejected
- Candidate dataset: DANDI:000488 Allen Institute OpenScope Predictive-Coding Two-Photon GCaMP ROI ΔF/F Traces (processing/ophys/dff/traces) Float64
- Source: https://dandiarchive.org/dandiset/000488/0.230602.2022
- Why it looked promising: see `pipeline/cards/dandi_000488_openscope_2p_dff_traces_f64.md`
- Failure class: autocollect driver limit
- What happened: byte-level breadth: every primary series is compression- and feature-equivalent to an existing family: openscope_roi_dff_traces_f64 ~ local:gfz_gracefo_fgm_acal_bnec_f64:gracefo_fgm_acal_corr_b_nec_f64 (distance 0.048, loss +0.006)
- Evidence:
  - 2026-10-09T01:02:28 proposed: {"log": ".data/pipeline/logs/scout_64bit/scout.20261009_004435.jsonl"}
  - 2026-10-09T01:05:15 screened: {"decision": "approve", "reason": "New at 64 bits: calcium_roi_traces exists only at 32 bits (raw Suite2p F from zebrafish), and this is baseline-normalized Allen \u0394F/F from a different lab and pipeline. The license is verified as CC-BY-4.0 with OpenAccess, and the dandiset metadata carries no A
  - 2026-10-09T01:45:21 builder: {"phase": "author", "status": "ready_for_download", "log": ".data/pipeline/logs/dandi_000488_openscope_2p_dff_traces_f64/builder.20261009_012945.jsonl", "cost": 3.723612200000001}
  - 2026-10-09T01:48:41 download: {"rc": 0, "reason": "", "bytes": 488822475, "log": ".data/pipeline/logs/dandi_000488_openscope_2p_dff_traces_f64/download.20261009_014522.log"}
  - 2026-10-09T02:12:03 builder: {"phase": "build", "status": "ready_for_judge", "log": ".data/pipeline/logs/dandi_000488_openscope_2p_dff_traces_f64/builder.20261009_014958.jsonl", "cost": 7.248938399999999}
  - 2026-10-09T02:25:26 rebuild: {"ok": true}
- Logs: `.data/pipeline/logs/dandi_000488_openscope_2p_dff_traces_f64/`, `.data/logs/dandi_000488_openscope_2p_dff_traces_f64/`
- Decision: rejected
- Retry conditions: Retry only with material whose bytes differ measurably (zlsim.py gate) from the existing families.
