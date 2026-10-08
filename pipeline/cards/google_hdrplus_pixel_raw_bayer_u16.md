# Google HDR+ Burst Photography Dataset: Pixel/Pixel XL Raw Bayer CFA Sensor Frames (10-bit in 16-bit DNG), UInt16

- Candidate id: `google_hdrplus_pixel_raw_bayer_u16`
- Width: uint16
- Quantity: Raw camera sensor digital numbers (Bayer RGGB color-filter-array mosaic, 10-bit, WhiteLevel 1023, black level about 64) from the Sony IMX378 sensor in Google Pixel/Pixel XL phones. These are the as-captured burst input frames.
- Source: https://hdrplusdata.org/dataset.html
- Resources: https://storage.googleapis.com/storage/v1/b/hdrplusdata/o?prefix=20171106/bursts/&delimiter=/, https://storage.googleapis.com/hdrplusdata/20171106_subset/bursts/0006_20160722_115157_431/payload_N000.dng, https://storage.googleapis.com/hdrplusdata/README.html
- License: CC-BY-SA (Creative Commons Attribution-ShareAlike)
- License evidence: https://storage.googleapis.com/hdrplusdata/README.html
- License quote: The dataset is released under a Creative Commons license (CC-BY-SA). This license is broad and largely unencumbered, however our main intention is that the dataset be used for scientific purposes.
- Natural record: One complete raw burst frame: payload_N000.dng (or the reference frame) of one burst, a 4048x3036 CFA mosaic decoded from 192 lossless-JPEG 256x256 tiles. That is 12,289,728 uint16 values (about 24.6 MB) per sample.
- Estimated samples: 35
- Estimated primary values: 430,000,000
- Estimated download bytes: 240,000,000
- Estimated primary bytes: 860,000,000
- Decode path: curl the GCS JSON listing to enumerate bursts. A 64 KB range GET of each payload_N000.dng reads the TIFF IFD (Make/Model tag 'google sailfish'/'marlin'), so selection keeps Pixel/Pixel XL only. Then download the selected DNGs whole (6-7 MB each). Pure Python: parse the TIFF IFD (tags 322/323 tile size, 324/325 tile offsets/bytecounts, Compression=7, CFA tags 33421/33422), then decode each tile with a lossless-JPEG (ITU T.81 SOF3, Huffman plus predictor) decoder written in stdlib Python. Self-test it on synthetic LJ92 streams. Reassemble the tiles and emit row-major little-endian uint16 with no normalization. Expect roughly 20-60 s per frame in CPython.
- Novelty kind: new_modality
- Measurement type: raw_bayer_cfa_image
- Instrument line: google_pixel_imx378_camera2_raw
- Archive collection: storage.googleapis.com/hdrplusdata
- Novelty evidence: novelty.py --url hdrplusdata --terms hdrplus bayer dng burst: no recipe, registry, ledger or downstream matches, only the shared host storage.googleapis.com. The vocabulary has no camera-raw/CFA-mosaic type. The closest existing families are processed or monochrome detector images (TUM VI camera frames, fluorescence microscopy, radiographs), none with a 2x2 interleaved colour-channel lattice.
- Homogeneity: Restrict to one sensor: Pixel (sailfish) plus Pixel XL (marlin), which share the IMX378 and the 4048x3036 active area. Drop Nexus 5/6/5X/6P bursts, which differ in resolution and sensor. Take one frame per burst (N000) to avoid near-duplicates within a burst, and exclude digitally-zoomed pre-cropped bursts, which have different dimensions. All frames are 10-bit with the same black/white levels.
- Risks: (1) Personal data: the README says subjects include the authors' friends and family. Some bursts show people. Raw Bayer data is not directly viewable, but it is identifiable after demosaicing. A judge may require selecting landscape/architecture bursts (e.g. via the curated gallery or final.jpg thumbnails, which the builder cannot inspect automatically). (2) Pure-Python LJ92 decoding is the main build effort and is slow. (3) CC-BY-SA share-alike and the 'scientific purposes' intent statement (not a restriction) should be recorded. (4) Taking 35 frames is a 1 GB-cap tradeoff; the full dataset has thousands of Pixel bursts.
- Probe evidence: The GCS JSON API listing works anonymously: 153 bursts under 20171106_subset/bursts/, 3640 in the full set. A 64 KB range GET of payload_N000.dng (6,356,788 bytes) parsed IFD0: 4048x3036, BitsPerSample 16, Compression 7 (lossless JPEG), Photometric 32803 (CFA), 256x256 tiles x192, WhiteLevel 1023, Make 'google', Model 'sailfish'. The README.html license text was fetched.

Proposed by the autocollect scout on 2026-10-08 (transcript `.data/pipeline/logs/scout_16bit/scout.20261008_163746.jsonl`).
