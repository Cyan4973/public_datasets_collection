# TUM VI Visual-Inertial Benchmark: 1024x1024 16-bit Grayscale Camera Frames (uEye global-shutter, 12-bit MSB-aligned), EuRoC Export

- Candidate id: `tumvi_euroc_1024_cam_frames_u16`
- Width: uint16
- Quantity: Linear-response grayscale intensity of a global-shutter fisheye VIO camera, published as 16-bit PNG with 12-bit sensor codes MSB-aligned (values are multiples of 16, 832-65520 observed). Scenes: indoor rooms, corridors, slides, the magistrale hall and outdoor campus.
- Source: https://cvg.cit.tum.de/data/datasets/visual-inertial-dataset
- Resources: https://vision.in.tum.de/tumvi/exported/euroc/1024_16/, https://vision.in.tum.de/tumvi/exported/euroc/1024_16/dataset-room1_1024_16.tar, https://vision.in.tum.de/tumvi/exported/euroc/1024_16/dataset-outdoors1_1024_16.tar, https://vision.in.tum.de/tumvi/exported/euroc/1024_16/dataset-corridor4_1024_16.tar
- License: CC-BY-4.0
- License evidence: https://cvg.cit.tum.de/data/datasets/visual-inertial-dataset
- License quote: All data in the Visual Inertial Dataset is licensed under a Creative Commons 4.0 Attribution License (CC BY 4.0) and the accompanying source code is licensed under a BSD-2-Clause License.
- Natural record: One camera frame (mav0/cam1/data/<ns>.png, 1024x1024 = 1,048,576 uint16 values). Suggested bounded subset: the first ~12 complete PNG members of each of the 28 sequence tars (room1-6, corridor1-5, slides1-3, magistrale1-6, outdoors1-8), fetched as a byte-range prefix of ~13 MB per tar. Tar member order is non-chronological (hash order), so prefix frames spread across each sequence.
- Estimated samples: 336
- Estimated primary values: 352,321,536
- Estimated download bytes: 350,000,000
- Estimated primary bytes: 704,643,072
- Decode path: curl -r 0-N prefix of each tar, then pure-Python ustar header walk (512-byte headers, octal sizes), keeping only fully contained .png members. 16-bit grayscale PNG decode with zlib plus scanline unfilter (all 5 filter types), big-endian to little-endian. The decoder from tum_rgbd_depth_u16 is reusable; PNG chunk CRCs give integrity. Validate IHDR = 1024x1024, bit depth 16, color type 0, and values % 16 == 0.
- Novelty kind: new_source
- Novelty evidence: novelty.py --url https://vision.in.tum.de/tumvi/ --terms tumvi visual-inertial: host-only match with tum_rgbd_depth_u16 (different dataset, sensor and quantity: depth vs intensity); no recipe, registry, ledger or downstream matches. 16-bit terrestrial natural-scene photographic frames are absent: existing 16-bit camera material is space or astro detectors (Mastcam-Z, JWST, IRIS), microscopy or medical.
- Homogeneity: One camera model and mode (IDS uEye, 1024x1024, 20 Hz, 12-bit MSB-aligned in 16-bit, linear response, not vignette-corrected), one export product (exported/euroc/1024_16). cam1 only from the tar prefix. Scene variety without unit or scale change.
- Risks: Low 4 bits are always zero (native MSB-aligned 12-bit as published). This is honest to the source, but a judge could ask for the 512_16 product instead, which is 2x2-binned with values in steps of 4. Prefix selection depends on the tar member order of static 2018 files: pin member names, sizes and PNG CRCs, since the published tar MD5s cover whole tars only. Camera frames are a crowded image family at this width, though these are terrestrial VIO frames.
- Probe evidence: Directory listings: 28 euroc 1024_16 tars, 3.1-57 GB each, with .md5 siblings. The page states 'All images in the dataset have 16-bit intensity depth and linear response function'. Range GET of 3 MB of dataset-room1_1024_16.tar: first members dataset-room1_1024_16/mav0/cam1/data/1520530390903335995.png (964,205 bytes); decoded IHDR (1024,1024,16,gray), min 832, max 65520, 1014 distinct, all values % 16 == 0. outdoors1 tar prefix has the same structure (first PNG 1,081,111 bytes). The 512_16 variant was also probed (min 992, max 65520, values in steps of 4).

Proposed by the autocollect scout on 2026-10-06 (transcript `.data/pipeline/logs/scout_16bit/scout.20261006_035523.jsonl`).
