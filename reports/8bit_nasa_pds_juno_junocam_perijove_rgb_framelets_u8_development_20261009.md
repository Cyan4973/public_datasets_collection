# Juno JunoCam perijove lossless colour EDR uint8 development

## Outcome

Accepted `nasa_pds_juno_junocam_perijove_rgb_framelets_u8`. It holds 22 whole JunoCam colour (C-type) Experiment Data Records of Jupiter, one per third perijove from PJ03 to PJ72 (2016-12-11 to 2025-05-07). Each is the losslessly compressed (HUFFMAN) product closest to closest approach.

The family has 8-bit raw planetary camera DN in common with the accepted `nasa_pds_voyager_iss_saturn_raw_u8`. It differs in instrument, mission and generation process: a Kodak KAI-2020 CCD pushframe camera on a spinning spacecraft, reading 128-line BLUE/GREEN/RED filter-strip framelets, with on-board square-root companding. Voyager is a vidicon framing camera. Measured breadth puts the two at feature distance 0.0449, inside the 0.05 threshold, but compression loss 0.0524, outside 3%. The verdict is OK, not redundant. Novelty kind: new content in a known modality.

## Source and rights

- Source: NASA PDS Imaging Node, `https://planetarydata.jpl.nasa.gov/img/data/juno/`, volumes JNOJNC_0001-0035 (data set `JUNO-J-JUNOCAM-2-EDR-L0-V1.0`).
- Pins:
  - 35 `INDEX.TAB` files (39,612,793 bytes), size and MD5 in `volumes.tsv`.
  - 531 candidate labels, each MD5 taken from the INDEX `PRODUCT_LABEL_MD5CHECKSUM`.
  - 22 IMG files: size = LINES × 1648, MD5 from the label `IMAGE MD5_CHECKSUM`; all 22 agree with the volume `_md5.txt` lists.
  - Evidence: AAREADME (9,911 bytes, MD5 `78a1c737…`) and the EDR/RDR SIS (52,771 bytes, MD5 `d93d4042…`).
- Licence: NASA SMD open scientific data policy. The SPD-41a FAQ states that SMD scientific data should be released under CC0 where no other restriction applies. The AAREADME states no use restriction. This is the same rights basis as the accepted Voyager ISS, Mastcam-Z and Cassini VIMS PDS recipes.
- Credit: NASA / JPL-Caltech / SwRI / MSSS.

## Shape and conversion

- **Natural record:** one EDR product. The IMG is a headerless PDS3 IMAGE object: fixed 1648-byte records, ^IMAGE at record 1, no line prefix or suffix. The emitted sample is therefore the IMG content, byte for byte: LINES × 1648 unsigned 8-bit SQROOT-companded DN in acquisition order (BLUE, GREEN, RED framelets per exposure).
- **Label checks:** no transformation, tiling or splitting. Every label is checked for:
  - SQROOT, SAMPLING_FACTOR 1, HUFFMAN
  - FILTER_NAME (BLUE, GREEN, RED)
  - LINES = FILE_RECORDS, a multiple of 384
- **Selection:**
  - Highest product version across volumes.
  - C-type, target JUPITER, orbit a multiple of 3.
  - RATIONALE_DESC relative time within 60 minutes; no "invalid" or "partial" flag.
  - This gives 531 candidates over 25 perijoves. The HUFFMAN product closest to perijove is taken from each.
  - PJ48, PJ60 and PJ75 have no qualifying lossless product.
- **Exclusion rule (shared by build and verify):** drop a product if more than 2% of its lines are fully zero, one DN value holds more than 50% of pixels, or it has fewer than 32 distinct DN. Nothing tripped it.

## Accepted output

- Series: `junocam_perijove_rgb_lossless_dn_u8` (uint8, primary, native_numeric)
- Pinned products 22, emitted 22, excluded 0
- Primary values / bytes: 549,298,176
- Sample sizes: minimum 16,453,632 (PJ06, 9,984 lines), median 25,313,280, maximum 26,578,944 (16,128 lines)
- Perijoves: 3, 6, 9, 12, 15, 18, 21, 24, 27, 30, 33, 36, 39, 42, 45, 51, 54, 57, 63, 66, 69, 72, from 13 volumes (JNOJNC_0010-0033), versions V01-V03
- Time offset to closest approach 0-45 min; spacecraft altitude 3,404-62,466 km; TDI 1-6; exposure 3.2-19.2 ms
- Pooled DN levels: 256. Per-product distinct DN: 151-256. Mode share: 0.033-0.233. Fully zero lines: 0 in every product.
- Aggregate SHA-256 of the samples, concatenated in sorted filename order: `3af79b2eda9569fa69b46cb78f4ed4e4eae1a929d67efac3361f9b34b939e416`

## Judge checks

- **Gate:** `gate.py` PASS with no warnings.
- **verify.sh:** I ran it myself; PASS in 57 s. It re-derives candidates and selection independently, byte-compares all 22 samples with their IMG files, checks MD5s, index rows and the manifest totals.
- **build.sh:** I read build.py; it uses only local `.data/downloads` files and the recipe TSVs.
- **Bytes:** I inspected all 22 samples with stdlib Python.
  - H0 is 3.97-7.32 bits; mean DN 16-117.
  - Per-filter framelet means always order BLUE < GREEN < RED, which is consistent with Jupiter's colour through the JunoCam filter strips.
  - DN 255 is at most 0.02% of pixels.
  - lzma ratio 0.30-0.41; line-delta entropy 2.2-2.9 bits.
- **Lossless claim:** I ran an 8×8 block test.
  - Horizontal |diff| is flat across column phase mod 8 (under 1% variation).
  - The only elevated vertical phase is the 128-line BLUE/GREEN/RED framelet boundary.
  - So the products are lossless, not ICT.
- **PJ06 mode share (23% zeros):** this is dark sky in a north-pole view from 62,000 km, the same camera process. No fill warning was raised.
- **Edge columns:** roughly 50-60% zero in many products. This is native detector border material; it is kept and documented.
- **Rights:**
  - I fetched the science.nasa.gov SMD policy page and the SPD-41a FAQ (CC0 statement).
  - The rights basis matches the accepted NASA PDS recipes.
  - No credentials in any script; no personal data.
- **Novelty:**
  - `novelty.py --url/--terms`: no Juno material locally, in the registry, the ledger (apart from this candidate) or downstream. The only URL neighbour is the unaccepted staging draft `nasa_pds_cassini_iss_nac_lut8_raw_u8` (different mission and instrument).
  - The breadth-key query shows raw_space_frame at 8 bits only for Voyager ISS and IUE SWP; nothing shares the instrument line or archive collection.
  - Measured zlsim verdict OK.
- **Minor documentation note:** the README's pre-build probe text ("zero fractions of 0.0-12%, mode shares of at most 20%") understates PJ06's realized 23.3% zero/mode share. The text is framed as probe results with "the build is authoritative", and the manifest and builder summary report the realized numbers. Not a defect in scope or output.
