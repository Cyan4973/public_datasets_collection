# nihcc_chestxray14_frontal_radiograph_png_u8

- Date: 2026-10-08
- Status: rejected
- Candidate dataset: NIH Clinical Center ChestX-ray14: Frontal Chest Radiographs (1024x1024 8-bit grayscale PNG) UInt8
- Source: https://nihcc.app.box.com/v/ChestXray-NIHCC
- Why it looked promising: see `pipeline/cards/nihcc_chestxray14_frontal_radiograph_png_u8.md`
- Failure class: autocollect driver limit
- What happened: byte-level breadth: every primary series is compression- and feature-equivalent to an existing family: chestxray14_frontal_radiograph_u8 ~ local:nasa_pds_voyager_iss_saturn_raw_u8:vg2_issn_saturn_raw_dn_u8 (distance 0.0443, loss -0.045)
- Evidence:
  - 2026-10-06T04:00:46 proposed: {"log": ".data/pipeline/logs/scout_8bit/scout.20261006_034137.jsonl"}
  - 2026-10-08T15:42:39 screened: {"decision": "approve", "reason": "No 8-bit projection radiograph family exists; the only chest radiograph family is TCIA u16 from a different source and pipeline. The NIH CC FAQ states 'usage of the data set is unrestricted' with attribution, from a US federal agency, and the images are de-identifi
  - 2026-10-08T15:52:52 builder: {"phase": "author", "status": "ready_for_download", "log": ".data/pipeline/logs/nihcc_chestxray14_frontal_radiograph_png_u8/builder.20261008_154239.jsonl", "cost": 2.386886600000001}
  - 2026-10-08T15:53:53 download: {"rc": 0, "reason": "", "bytes": 176245361, "log": ".data/pipeline/logs/nihcc_chestxray14_frontal_radiograph_png_u8/download.20261008_155252.log"}
  - 2026-10-08T16:26:56 builder: {"phase": "build", "status": "ready_for_judge", "log": ".data/pipeline/logs/nihcc_chestxray14_frontal_radiograph_png_u8/builder.20261008_162337.jsonl", "cost": 4.731242600000001}
  - 2026-10-08T16:45:13 rebuild: {"ok": true}
- Logs: `.data/pipeline/logs/nihcc_chestxray14_frontal_radiograph_png_u8/`, `.data/logs/nihcc_chestxray14_frontal_radiograph_png_u8/`
- Decision: rejected
- Retry conditions: Retry only with material whose bytes differ measurably (zlsim.py gate) from the existing families.
