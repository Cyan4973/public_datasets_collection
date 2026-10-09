# Martian Nakhlite Meteorite EBSD Maps (Oxford HKL CHANNEL5 .ctf, Zenodo 5545821): Native 8-bit Per-Pixel Band Contrast (BC) and Band Slope (BS) Pattern-Quality Maps, UInt8

- Candidate id: `zenodo_nakhlite_ebsd_band_contrast_slope_u8`
- Width: uint8
- Quantity: Per-scan-point EBSD Kikuchi pattern-quality measures from the Oxford HKL CHANNEL5 indexer: Band Contrast (BC, 0-255, the Hough-peak intensity of the detected bands relative to background) and Band Slope (BS, 0-255, the sharpness of the band edges). Grid maps at 2.5-15 um step over nakhlite thin sections at 20 kV and 70 deg tilt.
- Source: https://zenodo.org/records/5545821
- Resources: https://zenodo.org/api/records/5545821, https://zenodo.org/api/records/5545821/files/NWA998_UG1.ctf/content, https://zenodo.org/api/records/5545821/files/Y749_72A.ctf/content, https://zenodo.org/api/records/5545821/files/NWA998_T1.ctf/content, https://zenodo.org/api/records/5545821/files/Y802_36A.ctf/content, https://zenodo.org/api/records/5545821/files/Y593_127A.ctf/content, https://zenodo.org/api/records/5545821/files/GV_BM1975M16P19783.ctf/content, https://zenodo.org/api/records/5545821/files/MIL%20090136_50.ctf/content, https://zenodo.org/api/records/5545821/files/Y593_106A.ctf/content, https://zenodo.org/api/records/5545821/files/Lafayette_USNM1505-5_LAM.ctf/content, https://zenodo.org/api/records/5545821/files/Y749_64A.ctf/content
- License: CC-BY-4.0
- License evidence: https://zenodo.org/api/records/5545821
- License quote: Record metadata: "license": {"id": "cc-by-4.0"}. Description: "Martian nakhlite meteorite electron backscatter data and magma body unit thickness calculation code." The .ctf files are the deposited data objects.
- Natural record: One EBSD map (one .ctf file = one thin-section scan). BC and BS are emitted in raster order (XCells x YCells from the header) as two primary series, one sample per map per series.
- Estimated samples: 10
- Estimated primary values: 61,600,000
- Estimated download bytes: 1,935,200,000
- Estimated primary bytes: 61,600,000
- Decode path: curl the 10 pinned CHANNEL5-style .ctf text files (sizes pinned from the Zenodo API). Stdlib Python: read the header up to the 'Phase X Y Bands Error Euler1 Euler2 Euler3 MAD BC BS' column line and take XCells/YCells; split rows on tabs; BC = int(col 9), BS = int(col 10); check 0<=v<=255 and that the row count equals XCells*YCells; write bytes(). Phase/X/Y/Euler/MAD are optional auxiliaries.
- Novelty kind: new_quantity
- Measurement type: ebsd_indexing_quality_map
- Instrument line: oxford_hkl_channel5_ebsd
- Archive collection: zenodo
- Novelty evidence: novelty.py --url https://zenodo.org/records/5545821 --terms EBSD 'band contrast' nakhlite ctf: no URL match (same host only) and no band-contrast or nakhlite matches. 'EBSD' matches only zenodo_nordif_ebsd_kikuchi_patterns_u8 (raw Kikuchi detector frames, a different quantity and record) and zenodo_silicon_diffraction_tiff_u16. No indexing-quality map family exists locally or downstream. zlsim feature probe (my /tmp script calling zlsim.sample_features plus percentile_distance against the 8-bit library). BC chunks from 3 maps: nearest 0.107 (asterisk mulaw), 0.063 (EM302 water column), 0.090 (MODIS FPAR). BS: nearest 0.091 (FPAR). Probe noise is about 0.05.
- Homogeneity: Restricted to the 10 maps exported by legacy CHANNEL5 (header 'Device 0', 4-decimal steps, 20 kV, 70 deg tilt). Excluded from the same record: the 9 AZtec-exported maps ('Device 1', different software and likely detector, so BC scaling differs), the 0.4 um-step NWA 817 map and the terrestrial Caleta El Cobre map. All kept maps are nakhlite thin sections from one petrofabric study.
- Risks: (1) Only 10 samples (one small 93k-pixel map), forced by the homogeneity restriction. (2) Moderate gate margin: probe distances 0.063-0.107 on ~10k-value chunks, with ~0.05 probe noise. (3) Non-indexed or off-sample pixels have BC=BS=0: zero share 0.1%, 12% and 28% in the three maps sampled, well under the 0.8 flag; verify should report it. (4) ~1.9 GB of text download for ~62 MB of primary bytes. Tolerable since the kept signal is large and there is no binary alternative in this record. (5) Two primary series from the same rows: if the judge wants one quantity, keep BC primary.
- Probe evidence: Zenodo API lists 22 files with sizes. 1.5 KB range GETs of every .ctf header (XCells/YCells/XStep/Device/KV) fixed the CHANNEL5 vs AZtec split. Mid-file ranges parsed cleanly: NWA998_T1 6,317 rows (BC 0-109 with 92 distinct values, BS 0-94); Y749_64A 9,512 rows (BC max 128, zero share 0.001); MIL 090136_50 9,755 rows (zero share 0.283). Total transfer about 2 MB.

Proposed by the autocollect scout on 2026-10-09 (transcript `.data/pipeline/logs/scout_8bit/scout.20261009_114820.jsonl`).
