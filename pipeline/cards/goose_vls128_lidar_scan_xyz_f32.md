# GOOSE Off-Road Driving Dataset Velodyne VLS-128 LiDAR Sweep Point Coordinates (x,y,z) Float32

- Candidate id: `goose_vls128_lidar_scan_xyz_f32`
- Width: float32
- Quantity: Per-point Cartesian coordinates x, y, z (metres, sensor frame) of complete 128-beam Velodyne VLS-128 sweeps recorded from the MuCAR-3 research vehicle driving unstructured off-road terrain in Bavaria (2022-2023).
- Source: https://goose-dataset.de/docs/setup/
- Resources: https://goose-dataset.de/storage/goose_3d_val.zip, https://owncloud.fraunhofer.de/index.php/s/bpH7050VITEVnme/download, https://goose-dataset.de/storage/goose_3d_test.zip
- License: CC-BY-SA-4.0
- License evidence: https://goose-dataset.de/docs/setup/
- License quote: "The GOOSE Datset is published under the CC BY-SA 4.0 License." (download page). The LICENSE member inside goose_3d_val.zip begins "Attribution-ShareAlike 4.0 International", and the GitHub README says "The data is published under the CC BY-SA 4.0 License."
- Natural record: One LiDAR sweep file lidar/val/<sequence>/<seq>__NNNN_<ns>_vls128.bin (KITTI layout, N x 4 little-endian float32 x,y,z,intensity; median about 194k points). Emit N x 3 xyz float32 per sweep. Intensity is integer-valued 0-255 stored as float, so keep it auxiliary or drop it.
- Estimated samples: 64
- Estimated primary values: 37,000,000
- Estimated download bytes: 186,000,000
- Estimated primary bytes: 140,000,000
- Decode path: Read the zip central directory: 1,925 entries at offset 3,498,107,450, 294,887 bytes, no ZIP64 needed. All .bin members are stored uncompressed (method 0). For each selected member, range-GET the local header plus data with curl, skip the 30+name+extra bytes, read raw float32 LE, take 12 of every 16 bytes per point. Pure stdlib struct.
- Novelty kind: new_modality
- Novelty evidence: novelty.py --url https://goose-dataset.de/storage/goose_3d_val.zip --terms goose lidar vls128 'point cloud': no URL match and no 32-bit hits. Lidar matches are only the airborne DC LAS families at 8/16/64 bits (classification u8, intensity u16, GPS time f64). Local 32-bit point-like families are CAD mesh vertices (modelnet10), atom coordinates and building footprints, not vehicle-mounted spinning-lidar sweeps.
- Homogeneity: Single sensor model (all 961 val members end in _vls128.bin), single vehicle platform, one unit (m), one generation process (raw sweep). Primary is xyz only. Suggest 8 evenly spaced sweeps from each of the 8 val sequences (garching, aying, neubiberg sunny/rain, siegertsbrunn, 2022-07-22_flight...).
- Risks: Share-alike license (ExoMol CC BY-SA precedent treated as acceptable). xyz are interleaved per point (same unit, natural layout). Check for zero/padding points and NaNs. The GOOSE-Ex sibling uses other platforms and sensors, so don't mix it in. The 3.5 GB zip needs range fetching rather than full download.
- Probe evidence: HEAD goose_3d_val.zip: HTTP 200, content-length 3,498,402,435, accept-ranges bytes, last-modified 2025-03-19. Central directory parsed: 961 .bin (2,798,268,912 B; min 484,208, median 3,112,208, max 4,331,520), 961 .label, LICENSE, CHANGELOG ('2024-07-26: Initial upload of GOOSE 3D with 9892 annotated LiDAR scenes'), goose_label_mapping.csv. Eight sequences, 73-191 sweeps each. Range-read the first points of one member: (-1.156,-0.130,-0.543,22.0), (-6.663,-0.744,-2.385,7.0), (-8.380,-0.925,-2.424,12.0).

Proposed by the autocollect scout on 2026-10-06 (transcript `.data/pipeline/logs/scout_32bit/scout.20261005_234311.jsonl`).
