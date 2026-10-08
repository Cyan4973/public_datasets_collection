# ric_treadmill_running_marker_trajectories_f64

- Date: 2026-10-08
- Status: rejected
- Candidate dataset: Running Injury Clinic (Calgary) Treadmill Running 3D Marker Trajectories Float64
- Source: https://plus.figshare.com/articles/dataset/Running_Injury_Clinic_Kinematic_Dataset/24255795
- Why it looked promising: see `pipeline/cards/ric_treadmill_running_marker_trajectories_f64.md`
- Failure class: autocollect driver limit
- What happened: byte-level breadth: every primary series is compression- and feature-equivalent to an existing family: running_marker_xyz_f64 ~ local:orex_ola_l2_lidar_point_xyz_f64:ola_l2_return_xyz_f64 (distance 0.0396, loss +0.006)
- Evidence:
  - 2026-10-06T02:59:10 proposed: {"log": ".data/pipeline/logs/scout_64bit/scout.20261006_023838.jsonl"}
  - 2026-10-06T03:09:10 screened: {"decision": "approve", "reason": "New source: the figshare+ article 24255795 API confirms CC BY 4.0 (also stated in the README). ndownloader answered a one-byte range GET with 206, and the 22.7 GB ZIP is range-addressable per member. There is no mocap family at 64-bit locally, downstream or in this
  - 2026-10-06T03:31:18 builder: {"phase": "author", "status": "ready_for_download", "log": ".data/pipeline/logs/ric_treadmill_running_marker_trajectories_f64/builder.20261006_031058.jsonl", "cost": 4.345144400000001}
  - 2026-10-06T03:49:38 download: {"rc": 0, "reason": "", "bytes": 726732969, "log": ".data/pipeline/logs/ric_treadmill_running_marker_trajectories_f64/download.20261006_033118.log"}
  - 2026-10-06T04:09:13 builder: {"phase": "build", "status": "ready_for_judge", "log": ".data/pipeline/logs/ric_treadmill_running_marker_trajectories_f64/builder.20261006_035435.jsonl", "cost": 6.3555024}
  - 2026-10-06T04:16:22 rebuild: {"ok": true}
  - 2026-10-08T16:03:06 rebuild: {"ok": true}
- Logs: `.data/pipeline/logs/ric_treadmill_running_marker_trajectories_f64/`, `.data/logs/ric_treadmill_running_marker_trajectories_f64/`
- Decision: rejected
- Retry conditions: Retry only with material whose bytes differ measurably (zlsim.py gate) from the existing families.
