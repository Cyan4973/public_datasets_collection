# icon_mighti_l22_thermospheric_vector_wind_f64

- Date: 2026-10-08
- Status: rejected
- Candidate dataset: ICON MIGHTI Level-2.2 Green-Line (557.7 nm) Thermospheric Horizontal Vector Wind Profiles (Zonal / Meridional) Float64
- Source: https://gov-nasa-hdrl-data1.s3.amazonaws.com/spdf/cdaweb/data/icon/l2-2_mighti_vector-wind-green/
- Why it looked promising: see `pipeline/cards/icon_mighti_l22_thermospheric_vector_wind_f64.md`
- Failure class: autocollect driver limit
- What happened: byte-level breadth: every primary series is compression- and feature-equivalent to an existing family: icon_mighti_l22_green_zonal_wind_f64 ~ local:orex_ola_l2_lidar_point_xyz_f64:ola_l2_return_xyz_f64 (distance 0.0437, loss +0.009); icon_mighti_l22_green_meridional_wind_f64 ~ local:icon_ivm_a_l27_ion_drift_velocity_f64:ivm_a_ion_drift_velocity_f64 (distance 0.0399, loss +0.008)
- Evidence:
  - 2026-10-06T04:15:05 proposed: {"log": ".data/pipeline/logs/scout_64bit/scout.20261006_034331.jsonl"}
  - 2026-10-08T15:42:39 screened: {"decision": "approve", "reason": "New modality: remote-sensed thermospheric neutral wind profiles, absent everywhere (novelty.py is clean). Rights basis is the same as the ICON IVM candidate (NASA CC0 default; Rules of the Road: no restrictions). The S3 object answers a range request (206). Values
  - 2026-10-08T16:00:48 builder: {"phase": "author", "status": "ready_for_download", "log": ".data/pipeline/logs/icon_mighti_l22_thermospheric_vector_wind_f64/builder.20261008_154239.jsonl", "cost": 4.5331638000000005}
  - 2026-10-08T16:02:35 download: {"rc": 0, "reason": "", "bytes": 242824920, "log": ".data/pipeline/logs/icon_mighti_l22_thermospheric_vector_wind_f64/download.20261008_160134.log"}
  - 2026-10-08T16:28:28 builder: {"phase": "build", "status": "ready_for_judge", "log": ".data/pipeline/logs/icon_mighti_l22_thermospheric_vector_wind_f64/builder.20261008_162337.jsonl", "cost": 7.505531200000001}
  - 2026-10-08T17:19:52 rebuild: {"ok": true}
- Logs: `.data/pipeline/logs/icon_mighti_l22_thermospheric_vector_wind_f64/`, `.data/logs/icon_mighti_l22_thermospheric_vector_wind_f64/`
- Decision: rejected
- Retry conditions: Retry only with material whose bytes differ measurably (zlsim.py gate) from the existing families.
