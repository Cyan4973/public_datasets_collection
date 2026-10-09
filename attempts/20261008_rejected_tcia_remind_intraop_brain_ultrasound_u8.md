# tcia_remind_intraop_brain_ultrasound_u8

- Date: 2026-10-08
- Status: rejected
- Candidate dataset: ReMIND Brain-Resection Intraoperative 3D Ultrasound Volumes (US_pre_dura sweeps, uncompressed 8-bit DICOM) UInt8
- Source: https://doi.org/10.7937/3RAG-D070
- Why it looked promising: see `pipeline/cards/tcia_remind_intraop_brain_ultrasound_u8.md`
- Failure class: autocollect driver limit
- What happened: byte-level breadth: every primary series is compression- and feature-equivalent to an existing family: remind_us_pre_dura_volume_u8 ~ local:covertype_uci:cov_col_23 (distance 0.0, loss +0.000)
- Evidence:
  - 2026-10-08T17:05:55 proposed: {"log": ".data/pipeline/logs/scout_8bit/scout.20261008_162656.jsonl"}
  - 2026-10-08T17:08:28 screened: {"decision": "approve", "reason": "ReMIND (DOI 10.7937/3RAG-D070) is new to the corpus. DataCite and all 320 NBIA US series rows say CC BY 4.0. getSeries is live: 104 US_pre_dura series, 7.99 GB total, about 77 MB each, so about 12-13 complete volumes fit under the cap. Unlike HC18 2D fetal B-mode,
  - 2026-10-08T17:22:24 breadth_approved: {"note": "user approved 3rd TCIA family: different modality (ultrasound) and width"}
  - 2026-10-08T17:33:07 builder: {"phase": "author", "status": "ready_for_download", "log": ".data/pipeline/logs/tcia_remind_intraop_brain_ultrasound_u8/builder.20261008_172404.jsonl", "cost": 2.0552159999999997}
  - 2026-10-08T17:37:59 download: {"rc": 0, "reason": "", "bytes": 973063607, "log": ".data/pipeline/logs/tcia_remind_intraop_brain_ultrasound_u8/download.20261008_173440.log"}
  - 2026-10-08T18:03:50 builder: {"phase": "build", "status": "ready_for_judge", "log": ".data/pipeline/logs/tcia_remind_intraop_brain_ultrasound_u8/builder.20261008_174750.jsonl", "cost": 4.117017000000001}
  - 2026-10-08T18:05:22 rebuild: {"ok": true}
- Logs: `.data/pipeline/logs/tcia_remind_intraop_brain_ultrasound_u8/`, `.data/logs/tcia_remind_intraop_brain_ultrasound_u8/`
- Decision: rejected
- Retry conditions: Retry only with material whose bytes differ measurably (zlsim.py gate) from the existing families.
