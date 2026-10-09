# Juno JunoCam Perijove Colour EDRs: Raw 8-bit Pushframe Framelet Strips (BLUE/GREEN/RED, 1648 px wide) UInt8

- Candidate id: `nasa_pds_juno_junocam_perijove_rgb_framelets_u8`
- Width: uint8
- Quantity: JunoCam detector DN (8-bit, square-root companded on board) for every pixel of a perijove colour (C-type) pushframe EDR: 1648-sample lines grouped into 128-line framelets cycling through the BLUE, GREEN and RED filter strips, stored as decompressed IMG in archive order.
- Source: https://planetarydata.jpl.nasa.gov/img/data/juno/
- Resources: https://planetarydata.jpl.nasa.gov/img/data/juno/JNOJNC_0005_md5.txt, https://planetarydata.jpl.nasa.gov/img/data/juno/JNOJNC_0005/DATA/EDR/JUPITER/ORBIT_07/?C=S;O=D, https://planetarydata.jpl.nasa.gov/img/data/juno/JNOJNC_0005/DATA/EDR/JUPITER/ORBIT_07/JNCE_2017192_07C00056_V01.IMG, https://planetarydata.jpl.nasa.gov/img/data/juno/JNOJNC_0012/DATA/EDR/JUPITER/
- License: NASA SMD open scientific data (NASA PDS mission data, US Government work, no copyright)
- License evidence: https://science.nasa.gov/researchers/science-data/science-information-policy/
- License quote: information produced from SMD-funded scientific research activities be made publicly available ... Mission data are released as soon as possible
- Natural record: One JunoCam colour EDR product (one IMG = one pushframe image strip, LINES x 1648 bytes, no embedded header; detached PDS3 .LBL gives LINES/LINE_SAMPLES/SAMPLE_BITS=8/FILTER_NAME).
- Estimated samples: 30
- Estimated primary values: 500,000,000
- Estimated download bytes: 510,000,000
- Estimated primary bytes: 500,000,000
- Decode path: curl the .LBL and .IMG. Parse the PDS3 label with stdlib regex: LINES, LINE_SAMPLES=1648, SAMPLE_BITS=8, SAMPLE_TYPE=UNSIGNED_INTEGER, FILTER_NAME=('BLUE','GREEN','RED'), TARGET_NAME=JUPITER. Check that the IMG size equals LINES*1648 (verified: the 1024-line product is exactly 1,687,552 bytes) and copy the bytes unchanged as uint8. Selection: C-type products only (filename _NNC), TARGET JUPITER, from perijove passes (largest products, 12-25 MB, e.g. ORBIT_07 day 2017-192 has about 10 products of 23-25 MB). Spread about 30 products over about 8 perijoves in different volumes, keeping only the highest V0n version of each product.
- Novelty kind: new_source
- Measurement type: raw_space_frame
- Instrument line: Juno JunoCam pushframe visible camera (Kodak KAI-2020 CCD, 8-bit companded)
- Archive collection: PDS Imaging Node planetarydata.jpl.nasa.gov/img/data/juno
- Novelty evidence: novelty.py --url .../juno/JNOJNC_0005/ --terms junocam JNOJNC: no matches in recipes, registry, ledger or downstream. No Juno material exists at any width. zlsim feature probe (sample_features + percentile_distance against the 294-family 8-bit library, read-only) on a 2 MB window of 07C00056: nearest family is video_chroma_cb_u8 at 0.076, then Cassini RPWS WBR at 0.085 and Voyager ISS at 0.128. All are above the 0.05 redundancy threshold. Delta entropy is 1.46 bits and lzma ratio 0.164, very different from the noisy raw-frame families.
- Homogeneity: One camera (JunoCam), one product type (EDR colour pushframe, 3-filter RGB framelets), one target (Jupiter at perijove), and one on-board pipeline (8-bit square-root companding, ICT compression then ground decompression). Exclude methane (M), cruise, Earth-flyby and moon products, and approach images that are mostly black sky.
- Risks: Products are ICT-decompressed (lossy on board), so 8x8 block structure is part of the material. That is the archived EDR, not a local transform. Later volumes re-release earlier orbits as V02/V03, so the builder must de-duplicate by product ID. A few products may have missing framelets (zero fill), so check the zero fraction. planetarydata.jpl.nasa.gov is a JS-free Apache listing and was responsive. Use resumable curl.
- Probe evidence: Directory listing shows JNOJNC_0001..0035 volumes plus md5 lists. JNOJNC_0005 md5 list: 3,948 Jupiter EDRs (2,192 C, 1,764 M). ORBIT_07 size-sorted listing: 539 C products, top 10 at 23-25 MB. JNOJNC_0012 holds re-released ORBIT_01..22 with 16-24 MB C products. Labels: LINES 1024/3072, LINE_SAMPLES 1648, SAMPLE_BITS 8, COMPRESSION_TYPE 'INTEGER COSINE TRANSFORM', FILTER_NAME ('BLUE','GREEN','RED'). A 2 MB range GET of 07C00056 returned 206: H0 6.2 bits, zero fraction 1.25%.

Proposed by the autocollect scout on 2026-10-09 (transcript `.data/pipeline/logs/scout_8bit/scout.20261009_085042.jsonl`).
