# ric_treadmill_running_marker_trajectories_f64

- Date: 2026-10-08
- Status: rejected
- Candidate dataset: Running Injury Clinic (Calgary) Treadmill Running 3D Marker Trajectories Float64
- Source: https://plus.figshare.com/articles/dataset/Running_Injury_Clinic_Kinematic_Dataset/24255795 (figshare+ 24255795 v2, CC BY 4.0)
- Why it looked promising: a new source of full-precision float64 motion-capture data (28 rigid-cluster markers, 200 Hz treadmill running) with a clean CC BY 4.0 license. Local mocap existed only at 32 bits (Fukuchi walking).
- Failure class: byte-level breadth (zlsim compression and feature equivalence)
- What happened: The recipe was completed and passed download, build, verify and gate.py. It range-reads members from the 22.7 GB ZIP64 with a pure-stdlib Deflate64 decoder, cross-checked with unzip. The walk took 100 sessions, one per subject, with the exact 28-marker set at 200 Hz (2014-2016; 108 toe-marker sessions skipped), giving 336,000,000 B of marker-major [28][5000][xyz] little-endian float64. The 2026-10-08 re-measurement with zlsim.py gate again returned redundant/WEAK. running_marker_xyz_f64 matches local:orex_ola_l2_lidar_point_xyz_f64 (distance 0.0355, loss +0.0058). naif_mro_sc_bus_attitude_ck_f64 angular rate (0.0368 / 0.0003) and monado_msd_valve_index_imu_f64 gyro (0.0451 / 0.0005) are also within the thresholds (distance 0.05, loss 0.03). Own ratio is 1.27: the processed doubles have noise-like low mantissa bits, so they compress like existing smooth f64 sensor and coordinate families.
- Evidence: .data/pipeline/logs/ric_treadmill_running_marker_trajectories_f64/zlsim_gate.20261008_153951.json; re-run on 2026-10-08 after the rebuild gave the same verdict; build, verify and gate logs under .data/logs/ric_treadmill_running_marker_trajectories_f64/
- Logs: `.data/pipeline/logs/ric_treadmill_running_marker_trajectories_f64/`, `.data/logs/ric_treadmill_running_marker_trajectories_f64/`
- Decision: rejected; reshaping the layout only to escape the similarity gate would be gaming it.
- Retry conditions: Retry only with material from this source whose bytes differ measurably under zlsim.py gate (e.g. a native lower-precision or integer-quantized kinematic representation published by the source), or if the zlsim library or thresholds change such that this series is no longer within 0.05 distance / 0.03 loss of an existing family.
