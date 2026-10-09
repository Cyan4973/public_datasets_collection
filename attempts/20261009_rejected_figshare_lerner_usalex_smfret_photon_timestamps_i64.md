# figshare_lerner_usalex_smfret_photon_timestamps_i64

- Date: 2026-10-09
- Status: rejected
- Candidate dataset: UCLA usALEX smFRET (Lerner/Weiss, lacCONS promoter RNAP studies) Photon-HDF5 Raw Photon Arrival Timestamps (photon_data/timestamps, 12.5 ns clock ticks) Int64
- Source: https://figshare.com/articles/dataset/usALEX-smFRET_raw_data_for_figure_2/5400769
- Why it looked promising: see `pipeline/cards/figshare_lerner_usalex_smfret_photon_timestamps_i64.md`
- Failure class: autocollect driver limit
- What happened: byte-level breadth: every primary series is compression- and feature-equivalent to an existing family: usalex_photon_timestamps_i64 ~ downstream:crossref_indexed_ts_u64 (distance 0.0449, loss +0.015)
- Evidence:
  - 2026-10-09T10:09:32 proposed: {"log": ".data/pipeline/logs/scout_64bit/scout.20261009_095354.jsonl"}
  - 2026-10-09T10:10:49 screened: {"decision": "approve", "reason": "New source. No usALEX/smFRET/Photon-HDF5 material in recipes, registry, ledger or downstream. The only URL overlap is the figshare host. CC BY 4.0 is set per article in the figshare v2 API on all three articles (5400769/5400793/5400901), which covers the attached .
  - 2026-10-09T10:23:23 builder: {"phase": "author", "status": "ready_for_download", "log": ".data/pipeline/logs/figshare_lerner_usalex_smfret_photon_timestamps_i64/builder.20261009_101237.jsonl", "cost": 2.7213110000000005}
  - 2026-10-09T10:25:11 download: {"rc": 0, "reason": "", "bytes": 269376358, "log": ".data/pipeline/logs/figshare_lerner_usalex_smfret_photon_timestamps_i64/download.20261009_102440.log"}
  - 2026-10-09T10:52:49 builder: {"phase": "build", "status": "ready_for_judge", "log": ".data/pipeline/logs/figshare_lerner_usalex_smfret_photon_timestamps_i64/builder.20261009_102902.jsonl", "cost": 1.2621406}
  - 2026-10-09T11:15:37 rebuild: {"ok": true}
- Logs: `.data/pipeline/logs/figshare_lerner_usalex_smfret_photon_timestamps_i64/`, `.data/logs/figshare_lerner_usalex_smfret_photon_timestamps_i64/`
- Decision: rejected
- Retry conditions: Retry only with material whose bytes differ measurably (zlsim.py gate) from the existing families.
