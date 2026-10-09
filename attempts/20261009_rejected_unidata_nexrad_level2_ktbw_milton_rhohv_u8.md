# unidata_nexrad_level2_ktbw_milton_rhohv_u8

- Date: 2026-10-09
- Status: rejected
- Candidate dataset: NOAA NEXRAD WSR-88D Level-II Dual-Polarization Correlation Coefficient (RHOHV) Moment Codes, KTBW Tampa Bay During Hurricane Milton (2024-10-09) UInt8
- Source: https://registry.opendata.aws/noaa-nexrad/
- Why it looked promising: see `pipeline/cards/unidata_nexrad_level2_ktbw_milton_rhohv_u8.md`
- Failure class: autocollect driver limit
- What happened: byte-level breadth: every primary series is compression- and feature-equivalent to an existing family: ktbw_l2_rhohv_codes_u8 ~ local:sevir_vil_storm_events_u8:sevir_vil_storm_event_cube_u8 (distance 0.0492, loss -0.016)
- Evidence:
  - 2026-10-09T00:54:34 proposed: {"log": ".data/pipeline/logs/scout_8bit/scout.20261009_004435.jsonl"}
  - 2026-10-09T01:02:57 screened: {"decision": "approve", "reason": "New polarimetric quantity (rho_hv); the corpus has only Level-III N0Q reflectivity, SEVIR VIL, and Doppler velocity at 8-bit. The NODD license on the AWS registry covers the unidata-nexrad-level2 bucket. Anonymous ListObjectsV2 works for 2024/10/09/KTBW/ (240 keys,
  - 2026-10-09T01:11:25 builder: {"phase": "author", "status": "ready_for_download", "log": ".data/pipeline/logs/unidata_nexrad_level2_ktbw_milton_rhohv_u8/builder.20261009_010257.jsonl", "cost": 1.8627463999999998}
  - 2026-10-09T01:13:37 download: {"rc": 0, "reason": "", "bytes": 1176336773, "log": ".data/pipeline/logs/unidata_nexrad_level2_ktbw_milton_rhohv_u8/download.20261009_011125.log"}
  - 2026-10-09T01:37:48 builder: {"phase": "build", "status": "ready_for_judge", "log": ".data/pipeline/logs/unidata_nexrad_level2_ktbw_milton_rhohv_u8/builder.20261009_011423.jsonl", "cost": 3.7630090000000003}
  - 2026-10-09T01:43:10 rebuild: {"ok": true}
- Logs: `.data/pipeline/logs/unidata_nexrad_level2_ktbw_milton_rhohv_u8/`, `.data/logs/unidata_nexrad_level2_ktbw_milton_rhohv_u8/`
- Decision: rejected
- Retry conditions: Retry only with material whose bytes differ measurably (zlsim.py gate) from the existing families.
