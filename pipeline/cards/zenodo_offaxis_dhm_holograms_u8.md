# Off-Axis Digital Holographic Microscopy (Lyncée common-mode DHM) Raw 2048x2048 Holograms of Unresolved Nanoparticles/Vesicles UInt8 (Zenodo 10632465 / Dryad 9cnp5hqr7)

- Candidate id: `zenodo_offaxis_dhm_holograms_u8`
- Width: uint8
- Quantity: Raw 8-bit camera intensity of off-axis interference holograms (carrier-fringe modulated) recorded by a common-mode off-axis DHM (KOALA software, 405 nm illumination) imaging nanoparticles, beads and lipid vesicles
- Source: https://zenodo.org/records/10632465
- Resources: https://zenodo.org/records/10632465/files/2022.10.17_12-45.zip?download=1, https://zenodo.org/records/10632465/files/2022.07.27_10-57_30nmAlO3_Flat.zip?download=1, https://zenodo.org/records/10632465/files/README.md?download=1, https://zenodo.org/api/records/10632465
- License: CC0-1.0
- License evidence: https://zenodo.org/api/records/10632465
- License quote: Zenodo record metadata: "license": {"id": "cc-zero"} (also published on Dryad, doi:10.5061/dryad.9cnp5hqr7, which is CC0 by policy)
- Natural record: One hologram frame (one TIFF, 2048x2048 = 4,194,304 uint8 pixels) from a DHM video; sample = one frame
- Estimated samples: 102
- Estimated primary values: 427,819,008
- Estimated download bytes: 560,000,000
- Estimated primary bytes: 427,819,008
- Decode path: curl range-fetch individual ZIP members (local header offsets read from the central directory at the zip tail; all zips < 4 GB, no zip64) -> zlib.decompressobj(-15) -> baseline TIFF parse (II, 8 bps, 1 spp, compression=5 LZW, predictor=2, 512 strips of 4 rows) -> pure-Python TIFF LZW decode + horizontal-differencing undo -> raw uint8 2048x2048. Verified end-to-end on 2022.10.17_12-45/Holograms/00124_holo.tif: 4,194,304 px decoded exactly.
- Novelty kind: new_modality
- Measurement type: digital_hologram
- Instrument line: lyncee_tec_common_mode_offaxis_dhm
- Archive collection: zenodo.org/records/10632465
- Novelty evidence: novelty.py --url https://zenodo.org/records/10632465 --terms hologram holographic DHM: no recipe, registry, ledger or downstream matches (Zenodo host only). No hologram/interferogram family at any width in the vocabulary. Byte statistics are unlike the smooth grayscale images that were rejected as redundant (EBSD/Voyager/hillshade neighbours): the carrier fringes have a period of about 3-4 px, so H0 = 7.49 bits, delta entropy = 7.97 bits (higher than H0, the reverse of natural images), and the zlib ratio is only 1.06.
- Homogeneity: One instrument (the same common-mode off-axis DHM and camera), one acquisition software, fixed 2048x2048 8-bit format. Restrict to the 405 nm videos: exclude 2022.08.02_14-37_AuFlat520 (520 nm changes fringe spacing). Flat and thick chambers share the same optics and fringe carrier. Take N evenly spaced frames per video (e.g. 6 per video x 17 videos), not contiguous frames.
- Risks: Frames within one video are temporally correlated (about 7 fps), so space the frames evenly across each video. The pure-Python LZW decoder is slow (~4 M px per frame), which is acceptable for about 100 frames. The fringe noise could land near a noise-like 8-bit family (e.g. Parkes filterbank) in zlsim. The 22 GB total source requires per-member range fetches rather than whole-zip downloads.
- Probe evidence: Zenodo API lists 19 files (18 zips, 0.56-1.65 GB each; README.md). A 1 MB tail range GET of 2022.10.17_12-45.zip returned the EOCD: 280 entries, 138 Holograms/*.tif (~5.28 MB compressed, 5,657,406 B uncompressed each) plus timestamps.txt. A range GET of one member (5.28 MB) was inflated and its TIFF IFD parsed: 256=2048, 257=2048, 258=8, 259=5, 317=2, 512 strips. Decoded pixel range 9..255, near-uniform histogram.

Proposed by the autocollect scout on 2026-10-08 (transcript `.data/pipeline/logs/scout_8bit/scout.20261008_182652.jsonl`).
