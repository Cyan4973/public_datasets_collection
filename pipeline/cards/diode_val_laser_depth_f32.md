# DIODE Dense Indoor/Outdoor Depth (FARO laser scanner) Validation Depth Maps, Native Float32 .npy (768x1024)

- Candidate id: `diode_val_laser_depth_f32`
- Width: float32
- Quantity: Per-pixel metric depth (m) from a FARO Focus S350 terrestrial laser scanner reprojected into 1024x768 camera views, indoor and outdoor scenes, stored upstream as '<f4' .npy arrays of shape (768, 1024, 1); invalid returns are 0 with a separate validity mask.
- Source: https://diode-dataset.org/
- Resources: http://diode-dataset.s3.amazonaws.com/val.tar.gz, https://github.com/diode-dataset/diode-devkit, https://raw.githubusercontent.com/diode-dataset/diode-devkit/master/diode_meta.json
- License: MIT
- License evidence: https://diode-dataset.org/
- License quote: "The DIODE dataset and the code is released using the MIT license." (diode-dataset.org, License section; devkit repo also MIT)
- Natural record: One depth view (*_depth.npy): 768x1024 float32 = 786,432 values, 3,145,728 bytes.
- Estimated samples: 160
- Estimated primary values: 125,829,120
- Estimated download bytes: 2,774,625,282
- Estimated primary bytes: 503,316,480
- Decode path: curl full val.tar.gz (2,774,625,282 B; README md5 5c895d09201b88973c8fe4552a67dd85) -> stdlib tarfile streaming (r|gz) -> select *_depth.npy members (skip *_depth_mask.npy, which mixes <f4/<f8, and RGB PNGs) using a deterministic, widely spaced view subset per scan (e.g. ~8 views per scan over 20 scans, both indoor and outdoor) -> parse npy v1 header (descr '<f4', shape (768,1024,1)) -> emit payload bytes unchanged as little-endian float32; masks may be auxiliary.
- Novelty kind: new_quantity
- Novelty evidence: novelty.py --url diode-dataset.s3.amazonaws.com/val.tar.gz --terms diode 'depth map' 'laser scanner': no URL match, no recipe/registry/ledger/downstream family; only downstream_registry hit is tum_rgbd_depth_u16 (Kinect depth at 16-bit). No depth-map family exists at 32-bit locally or downstream.
- Homogeneity: One sensor suite (FARO Focus S350 + same camera intrinsics), one projection pipeline, one unit (metres). Indoor (<~50 m) and outdoor (<~350 m) views differ in depth range but not in unit, sensor or generation process; keep both, or split if the builder prefers a tighter regime. Exclude normals, masks and RGB from primary.
- Risks: Val split covers only 6 scenes / 20 scans (612 views per devkit diode_meta.json); views of one scan overlap heavily, so the builder must choose widely spaced views to avoid near-duplicates; diversity is moderate. Whole 2.77 GB tar.gz must be downloaded (gzip not seekable) to keep ~0.5 GB (absolute kept signal is large; train split is 81 GB). Zero-valued invalid pixels must be documented as source missing-value encoding. Depth comes from a 360-degree scan reprojected into views (upstream-published, not local).
- Probe evidence: HEAD val.tar.gz -> 200, Content-Length 2,774,625,282, Last-Modified 2019-08-01; one-byte range GET -> 206. First 12 MB range gunzipped: tar members val/outdoor/scene_00022/scan_00196/..._depth.npy size 3,145,856 with header {'descr': '<f4', 'fortran_order': False, 'shape': (768, 1024, 1)}; _depth_mask.npy members are <f4 or <f8 (768,1024); RGB PNGs ~1.5 MB. diode_meta.json val: outdoor 3 scenes/10 scans/392 views, indoors 3 scenes/10 scans/220 views. Site license line verified; devkit GitHub license MIT.

Proposed by the autocollect scout on 2026-10-06 (transcript `.data/pipeline/logs/scout_32bit/scout.20261006_010748.jsonl`).
