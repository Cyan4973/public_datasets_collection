# HC18 Grand Challenge 2D Fetal-Head B-Mode Ultrasound Images (800x540 grayscale PNG) UInt8

- Candidate id: `zenodo_hc18_fetal_head_ultrasound_u8`
- Width: uint8
- Quantity: B-mode ultrasound echo brightness: 8-bit grayscale pixel intensities of standard trans-thalamic fetal-head plane sonograms acquired with GE Voluson E8 / Voluson 730 systems at Radboud UMC (pixel size 0.052-0.326 mm).
- Source: https://hc18.grand-challenge.org/
- Resources: https://zenodo.org/api/records/1327317/files/training_set.zip/content, https://zenodo.org/api/records/1327317/files/test_set.zip/content, https://zenodo.org/api/records/1327317/files/training_set_pixel_size_and_HC.csv/content, https://zenodo.org/api/records/1327317/files/test_set_pixel_size.csv/content
- License: CC-BY-4.0
- License evidence: https://zenodo.org/records/1327317
- License quote: Zenodo record 1327317 ('Automated measurement of fetal head circumference using 2D ultrasound images', van den Heuvel, de Bruijn, de Korte, van Ginneken): "license": {"id": "cc-by-4.0"}, access_right "open". The challenge site states no conflicting terms; it only asks to cite the PLoS ONE 2018 paper and the Zenodo dataset (DOI 10.5281/zenodo.1322000/1322001).
- Natural record: One 2D ultrasound image = one 800x540 uint8 grayscale frame (432,000 values). 999 training images (filenames up to 805; extra exams such as 010_2HC.png) and 335 test images.
- Estimated samples: 1,334
- Estimated primary values: 576,288,000
- Estimated download bytes: 176,445,301
- Estimated primary bytes: 576,288,000
- Decode path: Pure stdlib. Download both zips (133 MB + 43.5 MB), or range-read their central directories and fetch members. Select members matching *HC.png and exclude *_Annotation.png, the sonographer ellipse masks (labels, not primary). Members use stored (method 0) or deflate (method 8, use zlib.decompressobj(-15)). Parse PNG chunks and assert IHDR = 800x540, bit depth 8, colour type 0, interlace 0. Concatenate and zlib-inflate the IDAT data, undo per-scanline filters 0-4 (Paeth etc.), and write raw uint8 rows. Self-test the unfilter on synthetic PNGs. Pixel-size CSVs are auxiliary only.
- Novelty kind: new_modality
- Novelty evidence: novelty.py --url https://zenodo.org/records/1327317 --terms 'head circumference' and --terms hc18: no recipe, registry, ledger or downstream match; Zenodo is same-host only. --terms ultrasound matches only zenodo_rat_fus_image_sequence_f32 (32-bit functional-ultrasound Doppler power, different quantity and width) and figshare bat vocalizations (audio). The registry has a prior 8-bit ultrasound attempt, tcia_breast_lesions_usg_u8, blocked only because NBIA exposed no collection: the modality is wanted and still absent. No B-mode ultrasound exists among local, downstream or this effort's accepted 8-bit families.
- Homogeneity: Very homogeneous: one hospital (Radboud UMC), Voluson E8/730 systems, one standard plane (fetal head for HC measurement), and every image 800x540 8-bit grayscale. Training and test splits are the same material. Annotation masks are excluded.
- Risks: Clinical images (de-identified, published openly under CC BY 4.0 by the hospital team; a corner region is blacked out). The judge should accept this like the existing PhysioNet and TCIA medical recipes. Each image carries a small burned-in grey scale bar and corner masking (part of the published raster). Some subjects contribute 2-3 images (806 training subjects for 999 images). The builder must assert every image is 800x540 grayscale and fail on any RGB or other size. FETAL_PLANES_DB (Zenodo 3904280) was rejected as an add-on: RGBA, variable size, calliper overlays; do not mix.
- Probe evidence: Zenodo API: training_set.zip 132,926,838 B, test_set.zip 43,518,463 B, license cc-by-4.0. The training zip's central directory, read via range, has 1,999 entries (999 *HC.png + 999 *_Annotation.png + dir); 806 match _HC.png and the rest are _2HC/_3HC repeats. The test zip has 336 entries (335 images). Images are mostly stored (method 0), 100-160 kB each. Fetched 000_HC.png and 003_HC.png by range: IHDR 800x540, bit depth 8, colour type 0, non-interlaced. Visual check of 003_HC.png shows a clean B-mode fetal skull cross-section with speckle and no text overlays except a thin grey bar and a masked corner. The challenge page confirms 1,334 images (999/335), all 800x540.

Proposed by the autocollect scout on 2026-10-06 (transcript `.data/pipeline/logs/scout_8bit/scout.20261006_011511.jsonl`).
