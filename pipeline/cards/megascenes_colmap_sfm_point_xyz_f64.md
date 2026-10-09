# MegaScenes (Cornell/AWS Open Data) COLMAP Structure-from-Motion Reconstructions: Bundle-Adjusted 3-D Point XYZ (points3D.bin) Float64

- Candidate id: `megascenes_colmap_sfm_point_xyz_f64`
- Width: float64
- Quantity: Bundle-adjusted triangulated 3-D point coordinates (X,Y,Z, arbitrary SfM model frame) from COLMAP sparse reconstructions of Wikimedia Commons landmark photo collections
- Source: https://github.com/megascenes/dataset/blob/main/README.md
- Resources: https://megascenes.s3.us-west-2.amazonaws.com/?list-type=2&prefix=reconstruct/000/, https://megascenes.s3.us-west-2.amazonaws.com/reconstruct/000/007/colmap/0/points3D.bin, https://github.com/megascenes/datasheet/blob/main/README.md
- License: CC BY 4.0 (dataset; photos carry their own licenses and are not used)
- License evidence: https://github.com/megascenes/datasheet/blob/main/README.md
- License quote: "This dataset is licensed under the Creative Commons Attribution 4.0 International License. The photos in the dataset have their own licenses." (MegaScenes datasheet). The bucket is public via the AWS Open Data Sponsorship Program; README: 'Singular files can be downloaded over HTTP ... https://megascenes.s3.us-west-2.amazonaws.com/'.
- Natural record: One COLMAP reconstruction model (reconstruct/<sss>/<sss>/colmap/<k>/points3D.bin) gives one sample of N points x 3 float64 (XYZ interleaved, in file order). Optionally a second primary series holds the per-point float64 reprojection error.
- Estimated samples: 380
- Estimated primary values: 17,000,000
- Estimated download bytes: 445,000,000
- Estimated primary bytes: 135,000,000
- Decode path: download.sh: S3 ListObjectsV2 over prefix reconstruct/000/ (anonymous XML listing, 2 pages, 391 points3D.bin files totalling 445 MB). Pin the key list and sizes, drop models under ~32 KB (<~1000 values), and curl each points3D.bin. build: pure-stdlib struct. Header uint64 num_points; per point '<QdddBBBdQ' (id, x, y, z, r, g, b, error, track_len) = 51 bytes, followed by track_len*(uint32 image_id, uint32 point2D_idx). Emit x,y,z as f64 LE. Verified: reconstruct/000/007/colmap/0/points3D.bin (223,296 B) parses to exactly EOF with 2,840 points, full-mantissa coordinates (e.g. -5.557844868354845) and a mean track length of 3.45. Do NOT use images.bin keypoint xy: those are float32 SIFT locations widened to double.
- Novelty kind: new_modality
- Measurement type: sfm_point_cloud
- Instrument line: COLMAP incremental SfM on Wikimedia Commons photo collections (MegaScenes v1.0)
- Archive collection: aws_opendata_megascenes
- Novelty evidence: novelty.py --url/--terms (megascenes, colmap, structure-from-motion, points3D) finds no match in recipes, registry, ledger or downstream. No manifest mentions COLMAP. Photogrammetric SfM point clouds are absent at every width (measurement_type sfm_point_cloud: 0; archive aws_opendata_megascenes: 0). The nearest f64 families are ordered lidar/trajectory xyz streams (OLA lidar xyz, TUM pose). SfM points come in triangulation order with no spatial continuity, in a per-model arbitrary gauge/scale, so their delta statistics should differ from scan-ordered lidar.
- Homogeneity: One pipeline (COLMAP SfM run by the MegaScenes authors), one quantity (bundle-adjusted 3-D point position, float64), one file format. Each model has its own arbitrary similarity gauge, which is inherent to SfM and identical in generation process across samples. Multiple models per scene (colmap/0, colmap/1) are separate natural reconstructions.
- Risks: Byte-gate risk: may look compression-equivalent to orex_ola_l2_lidar_point_xyz_f64 (the RIC marker trajectories failed against it), though the unordered SfM sequence should make deltas far noisier. Primary is ~30% of the downloaded bytes (track arrays are discarded). This is acceptable with no leaner source, and the absolute kept signal is ~135 MB. The size distribution is heavy-tailed (median 255 KB, top model 48 MB); keep all models with natural boundaries. A few scenes may contain near-duplicate model pairs.
- Probe evidence: README and datasheet read via raw.githubusercontent. The S3 listing of reconstruct/000/007/ shows cameras.bin, images.bin, points3D.bin and project.ini for models 0 and 1. A full listing of reconstruct/000/ gave 391 points3D.bin files, 445.1 MB total, size quantiles p10 17.5 KB / p50 255 KB / p90 1.8 MB / p99 18.2 MB; 33 are over 2 MB (296 MB). One 223 KB file fetched and parsed exactly.

Proposed by the autocollect scout on 2026-10-09 (transcript `.data/pipeline/logs/scout_64bit/scout.20261009_095410.jsonl`).
