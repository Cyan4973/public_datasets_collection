# TartanAir V1 (CMU AirLab) Dense Optical-Flow Fields, Native Float32 .npy Frames (480x640x2 pixel displacement)

- Candidate id: `tartanair_optical_flow_f32`
- Width: float32
- Quantity: Dense forward optical flow between consecutive left-camera frames of the TartanAir visual-SLAM simulation dataset, (u, v) pixel displacement per pixel, stored upstream as little-endian float32 .npy arrays of shape (480, 640, 2) (members '<Pxxx>/flow/NNNNNN_MMMMMM_flow.npy' inside per-environment flow_flow.zip).
- Source: https://huggingface.co/datasets/theairlabcmu/tartanair
- Resources: https://huggingface.co/datasets/theairlabcmu/tartanair/resolve/65e00180ea952475878a748543e11e9ec20beaac/abandonedfactory/Easy/flow_flow.zip, https://huggingface.co/api/datasets/theairlabcmu/tartanair/tree/main?recursive=true, https://theairlab.org/tartanair-dataset/, https://github.com/castacks/tartanair_tools
- License: CC BY 4.0 (project site) / BSD-3-Clause (Hugging Face dataset card); both permissive
- License evidence: https://theairlab.org/tartanair-dataset/
- License quote: "This work is licensed under a Creative Commons Attribution 4.0 International License." (theairlab.org/tartanair-dataset); HF dataset card front-matter: "license: bsd-3-clause" (huggingface.co/datasets/theairlabcmu/tartanair, sha 65e00180ea95)
- Natural record: One optical-flow frame (one .npy member = flow from frame N to N+1 of one trajectory): 480x640x2 float32 = 614,400 values, 2,457,600 bytes.
- Estimated samples: 108
- Estimated primary values: 66,355,200
- Estimated download bytes: 315,000,000
- Estimated primary bytes: 265,420,800
- Decode path: curl -L range GET of the zip tail -> stdlib struct parse of ZIP64 EOCD record/locator and the ~2 MB central directory (zip64 extra field 0x0001 for sizes/offsets) -> pick evenly spaced *_flow.npy members (e.g. 3 per env/difficulty zip across the 36 flow_flow.zip files, spread over trajectories P000..P0xx) -> curl range GET of each member's local header + compressed bytes (~2.2 MB) -> zlib.decompressobj(-15) raw inflate -> parse .npy v1 header (ast.literal_eval of dict; verified descr '<f4', fortran_order False, shape (480, 640, 2)) -> emit the 2,457,600 payload bytes as little-endian float32 unchanged.
- Novelty kind: new_modality
- Novelty evidence: novelty.py --url huggingface.co/datasets/theairlabcmu/tartanair --terms tartanair 'optical flow' airsim: no URL/path match (same host only), no recipe/ledger/downstream term matches. Only registry hit is kubric_movi_optical_flow_f32 (rejected because Kubric stored flow as uint16 and lacked a data license); TartanAir stores native float32 flow and has explicit licenses, so neither rejection ground applies. No optical-flow family exists locally or downstream at any width.
- Homogeneity: Single generation process (AirSim/Unreal renderer, one pinhole camera model fx=fy=320, 640x480, same flow-computation pipeline) and single unit (pixels of displacement) across all environments; environments/difficulty only change scene content and motion magnitude. Emit only the flow arrays; flow_mask (uint8 occlusion masks), depth, RGB and poses stay out (or auxiliary).
- Risks: Synthetic: flow is an upstream simulation product computed from rendered depth + camera pose (stable published artifact, not a local numericization). Two different permissive license notices (CC BY 4.0 on site, BSD-3-Clause on HF card) — both permissive, cite both. flow zips are huge (4-63 GB each; 677 GB total) so the recipe must use zip64 range reads, never whole-zip downloads; HF resolve URLs redirect to signed xet CDN URLs (use -L per request; ranges returned 206). Builder should check for non-finite values and pin member CRC32s from the central directory.
- Probe evidence: HF API: theairlabcmu/tartanair public, not gated, sha 65e00180ea952475878a748543e11e9ec20beaac, 36 flow_flow.zip files (676.8 GB total). abandonedfactory/Easy/flow_flow.zip (34,137,856,465 B): 64 KiB tail range GET -> HTTP 206; ZIP64 EOCD: 15,530 entries, CD size 2,087,827 at offset 34,135,768,540; fetched CD: 15,488 *_flow.npy members all usize 2,457,728 (128-byte npy header + 2,457,600), deflate, mean csize 2.20 MB, across trajectories P000-P011. Range-fetched one member (P001/flow/000279_000280_flow.npy), raw-inflated: header {'descr': '<f4', 'fortran_order': False, 'shape': (480, 640, 2)}; first values -14.53, -1.34, ... (min/max of first 2000 values -17.5/9.0 px).

Proposed by the autocollect scout on 2026-10-06 (transcript `.data/pipeline/logs/scout_32bit/scout.20261006_010748.jsonl`).
