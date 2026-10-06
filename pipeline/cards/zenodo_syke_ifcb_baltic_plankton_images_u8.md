# SYKE-plankton_IFCB_2025: Imaging FlowCytobot (IFCB) Baltic Sea Phytoplankton ROI Images (8-bit grayscale PNG) UInt8

- Candidate id: `zenodo_syke_ifcb_baltic_plankton_images_u8`
- Width: uint8
- Quantity: 8-bit grayscale camera intensity of single-particle region-of-interest images from McLane Imaging FlowCytobot instruments (IFCB114, IFCB167): scatter/fluorescence-triggered flow-through imaging of Baltic Sea phytoplankton at Utö station and on Alg@line ferries, 2016-2024.
- Source: https://zenodo.org/records/17601020
- Resources: https://zenodo.org/api/records/17601020/files/Syke-plankton_IFCB_2025.zip/content, https://zenodo.org/api/records/17601020
- License: CC-BY-4.0
- License evidence: https://zenodo.org/records/17601020
- License quote: Zenodo record metadata: "license": {"id": "cc-by-4.0"} (Creative Commons Attribution 4.0 International). Description: 'If used in scientific applications, please aknowledge the authors/ creators of the dataset accordingly.'
- Natural record: One IFCB ROI image (one PNG member such as Syke-plankton_IFCB_2025_02/<class>/D20160902T073358_IFCB114_00068.png) = one particle image of variable size (e.g. 112x50, 192x42, 224x50). Median is about 12k pixels (PNG median 7.3 KB, p90 39 KB, max 876 KB), so it is above the 1,000-value median floor.
- Estimated samples: 8,000
- Estimated primary values: 250,000,000
- Estimated download bytes: 200,000,000
- Estimated primary bytes: 250,000,000
- Decode path: The zip (1,577,775,859 B) stores most PNGs uncompressed (57,776 method 0; 6,052 deflate), so members are byte-addressable. Fetch the EOCD and central directory (offset 1,565,993,651, size 11,782,110) with one range GET and parse it with struct (zip64-aware). For each of the ~139 class directories, take the first N (e.g. 60) PNG members; these are contiguous within a class run, so it costs one range request per class. Parse each local header, inflate method-8 members with zlib(-15), and decode the PNG with stdlib (IHDR, IDAT concat, zlib, filters 0-4). Keep bit_depth=8 and color_type=0; skip Thumbs.db, txt and the nested zip. Emit width*height uint8 values per image.
- Novelty kind: new_source
- Novelty evidence: novelty.py --url https://zenodo.org/records/17601020 --terms IFCB plankton flowcytobot syke: no recipe, registry, ledger, downstream or downstream_registry hits (Zenodo host-only URL match). There is no in-situ imaging-flow-cytometry or plankton imagery family in the corpus. Existing 8-bit microscopy is BBBC fluorescence or masks and electron or X-ray imaging (SBF-SEM, EBSD, SPED, micro-CT, K2 frames). Labeled new_source rather than new_modality because it is light-microscopy-adjacent.
- Homogeneity: One instrument model (McLane IFCB; units IFCB114 with 52,422 of the first 63,828 PNGs, IFCB167 with 11,406), one optical and camera chain, one 8-bit grayscale export. The taxonomic class only sets the folder; the pixel semantics are identical. Sampled images decode with backgrounds around 180-195 and 130-215 distinct levels per image (not flat). A per-class cap avoids dominance by Dolichospermum (10,372 images).
- Risks: (1) Microscopy-adjacent modality; 8-bit imaging is already broad in this effort, though no light or flow-imaging family is accepted yet. (2) Images are expert-curated, class-labeled training crops (a library, not every ROI of a bin), which is acceptable but a selection. (3) The full raw volume (~2.3 GB) exceeds the 1 GB cap, so the per-class bounded subset must be stated as the scope. (4) Many small samples (~8k); the median is well above the floor, so this is not aggregate salvage. (5) There are ~139-152 class folders; the builder must read the full central directory (11.8 MB) rather than the partial tail parsed during scouting.
- Probe evidence: Ranged GET 0-262143 returned 206; local headers showed stored PNG members (e.g. Akinete/D20160902T073358_IFCB114_00068.png method 0, 3,356 B, IHDR 112x50 bd=8 ct=0). Eight PNGs were decoded with a stdlib zlib/unfilter decoder: 112x50 with 175 distinct values (range 46-228), 192x42 with 215 distinct (24-241), etc. A ranged tail GET of the last 10 MiB returned 206; EOCD gives CD offset 1,565,993,651 and size 11,782,110, and 63,972 entries were parsed from the tail (63,828 PNG, 139 classes seen). The Zenodo API lists the zip at 1,577,775,859 bytes, md5 badd9f0db1bd4d6584f8a6125fb11763, published 2025-11-13.

Proposed by the autocollect scout on 2026-10-06 (transcript `.data/pipeline/logs/scout_8bit/scout.20261006_034137.jsonl`).
