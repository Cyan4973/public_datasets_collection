# Apple Hypersim Photorealistic Synthetic Indoor Scenes: Camera-Space Surface-Normal G-Buffers (normal_cam) Float16

- Candidate id: `apple_hypersim_normal_cam_f16`
- Width: float16
- Quantity: Per-pixel geometric surface normal vectors in camera space (unit 3-vectors, components in [-1,1]), as rendered by V-Ray for 768x1024 frames of Evermotion indoor scenes. Native IEEE binary16.
- Source: https://github.com/apple/ml-hypersim
- Resources: https://docs-assets.developer.apple.com/ml-research/datasets/hypersim/v1/scenes/ai_001_001.zip, https://raw.githubusercontent.com/apple/ml-hypersim/main/contrib/99991/download.py, https://raw.githubusercontent.com/apple/ml-hypersim/main/evermotion_dataset/analysis/metadata_images_split_scene_v1.csv
- License: CC BY-SA 3.0 Unported
- License evidence: https://github.com/apple/ml-hypersim/blob/main/README.md
- License quote: The Hypersim Dataset is licensed under the Creative Commons Attribution-ShareAlike 3.0 Unported License.
- Natural record: One rendered frame's normal_cam G-buffer (images/scene_cam_XX_geometry_hdf5/frame.NNNN.normal_cam.hdf5): a 768x1024x3 float16 array, 2,359,296 values (about 4.7 MB) per sample.
- Estimated samples: 100
- Estimated primary values: 236,000,000
- Estimated download bytes: 110,000,000
- Estimated primary bytes: 472,000,000
- Decode path: Each scene zip is about 2.2 GB, but its members are STORED (method 0), so the full zip is never downloaded. curl a range GET of the zip tail (EOCD plus central directory, about 0.5 MB), find the frame.NNNN.normal_cam.hdf5 member offset/size, and range-GET only that member (about 0.6 MB). The HDF5 uses a v0 superblock, a chunked layout with a v1 B-tree, and a deflate filter. Decode with a pure-stdlib HDF5 reader (the repo already has h5lite.py / well_h5.py chunked-deflate readers) plus zlib, then emit row-major little-endian float16 words unchanged. Use one frame per scene (e.g. a mid-trajectory frame of cam_00) over about 100 public-release scenes, using the split CSV to skip excluded scenes/cameras.
- Novelty kind: new_modality
- Measurement type: rendered_gbuffer
- Instrument line: vray_hypersim_render
- Archive collection: docs-assets.developer.apple.com/ml-research/datasets/hypersim
- Novelty evidence: novelty.py --url docs-assets.developer.apple.com/.../hypersim --terms hypersim depth_meters photorealistic: no matches anywhere, including downstream. No renderer G-buffer / surface-normal family exists. The 16-bit float families are OpenEXR half RGB radiance (ASWF), Poly Haven HDRI (staging) and BF16 LLM weights, none of which are unit-vector fields with piecewise-planar structure.
- Homogeneity: One quantity (normal_cam, not normal_bump or world-space), one renderer and pipeline, one resolution (768x1024x3), one scene corpus. Sky/no-hit pixels, if present, keep their native float16 (possibly NaN) bit patterns, with an explicit missing-value policy documented and checked in verify.
- Risks: (1) The builder must write or reuse a chunked-HDF5 reader. Existing repo readers cover deflate chunks, but v0-superblock/B-tree-v1 details need a self-test. (2) Possible NaN pixels need a documented policy. (3) The CC BY-SA 3.0 share-alike attribution must be preserved. Evermotion asset rights are not needed because only the published renders are used. (4) Only one Hypersim series should be taken; depth_meters or position from the same zips would not be a new family.
- Probe evidence: HEAD ai_001_001.zip: Content-Length 2,249,481,604, Accept-Ranges bytes. A tail range GET parsed 3344 central-directory entries, all method 0 (stored): 98 frames x {color, diffuse_illumination, ..., depth_meters, normal_cam, normal_world, position, ...}.hdf5. frame.0000.normal_cam.hdf5 is 591,967 bytes. A 3 KB range read of that member showed the HDF5 signature, a float datatype message with size 2 (0x11 0x20 0x0f 0x00 02 00 00 00, i.e. IEEE float16) and a deflate filter. depth_meters.hdf5 likewise uses chunked layout with a TREE node.

Proposed by the autocollect scout on 2026-10-08 (transcript `.data/pipeline/logs/scout_16bit/scout.20261008_163746.jsonl`).
