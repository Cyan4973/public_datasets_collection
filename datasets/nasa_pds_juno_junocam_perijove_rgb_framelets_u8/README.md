# Juno JunoCam perijove lossless colour EDRs (uint8)

This recipe collects 8-bit JunoCam detector DN rasters from 22 Jupiter colour pushframe
Experiment Data Records (EDRs), one per third perijove from PJ03 to PJ72 (2016-12 to 2025-05).
The source is the NASA PDS Imaging Node archive
(`https://planetarydata.jpl.nasa.gov/img/data/juno/`, volumes JNOJNC_0001-0035).

## Material

- **Instrument:** JunoCam, Kodak KAI-2020 interline CCD. The colour filter array is bonded
  to the detector. Juno's spin sweeps the BLUE, GREEN and RED strips across Jupiter, and
  each exposure reads one 128 x 1648 framelet per filter.
- **Product:** C-type (colour) EDR. `LINES x 1648` unsigned bytes, in the order frame 1
  BLUE/GREEN/RED, then frame 2, and so on (SIS 4.3.1.1).
- **Values:** 12-bit samples companded on board to 8 bits with the SQROOT table
  (`SAMPLE_BIT_MODE_ID = SQROOT`). The recipe does not decompand, flat-field or reproject.
- **Compression regime:** only products with `COMPRESSION_TYPE = HUFFMAN` are kept. The SIS
  calls this "Huffman (lossless)". Lossy ICT products (8x8 DCT block artifacts) and
  uncompressed `NONE` products are excluded so the family has a single regime. At perijove
  most C products are ICT, so lossless products are the smaller subset.
- **Scope:** within 45 minutes of closest approach, at 3,400-62,000 km altitude. Jupiter
  fills most of each framelet: belts, zones, jets and polar cyclones, with some limb and
  dark sky in the polar views.
- **Sample:** one sample per EDR, sized 9,984-16,128 lines (16-27 MB). Records are not
  split or tiled.

## Selection (re-derived by download, build and verify)

1. Read every `JUNOCAM-EDR` row of all 35 volume `INDEX.TAB` files. Keep the highest
   `_Vnn` version of each product ID (orbits up to 22 were re-released in JNOJNC_0004 and
   JNOJNC_0012 as V02/V03).
2. Keep a row as a candidate when all of these hold:
   - product type `C`
   - `TARGET_NAME = JUPITER` under `DATA/EDR/JUPITER/`
   - orbit is a positive multiple of 3
   - the `RATIONALE_DESC` relative time to its own perijove is within 60 minutes
   - the rationale does not contain "invalid" or "partial"

   This gives 531 candidates over 25 perijoves (`candidates.tsv`).
3. For each perijove, take the candidate whose label says `HUFFMAN` and has the smallest
   |relative time|. Ties go to the lowest product ID. This gives 22 products
   (`sources.tsv`).
   - PJ48, PJ60 and PJ75 have no qualifying lossless candidate.
   - The "partial" exclusion was added after range probes showed that the "partial"
     products for PJ39 and PJ60 were 31-34% zero-filled.
4. Exclusion rule, applied identically in build and verify: drop a product if more than
   2% of its lines are entirely zero (telemetry-loss fill, SIS 4.3.2), if one DN value
   holds more than 50% of its pixels, or if it has fewer than 32 distinct DN. Range probes
   of all 22 products (3 x 256 KB each) found zero fractions of 0.0-12% and mode shares of
   at most 20%. The zero values come mainly from dark sky and the zero border columns of
   each line. So all 22 are expected to pass, but the build is authoritative.

## Pins

- `volumes.tsv`: size and MD5 of the 35 `INDEX.TAB` files (39.6 MB).
- `candidates.tsv`: 531 label URLs. Each label MD5 comes from the INDEX.TAB
  `PRODUCT_LABEL_MD5CHECKSUM` column (all 531 matched at discovery).
- `sources.tsv`: 22 IMG URLs with size (= LINES x 1648, confirmed by HEAD) and MD5. The
  MD5 is the label `IMAGE MD5_CHECKSUM` and equals the volume `_md5.txt` entry for all 22.
- Evidence: `JNOJNC_0033/AAREADME.TXT` and the EDR/RDR SIS (`JUNO_JNC_EDR_RDR_DPSIS.HTM`).
- `discover.sh` regenerates the three TSVs (run 2026-10-09). The download path does not use it.

Expected download: 549,298,176 image bytes, plus 39,612,793 index bytes, 1,357,856 label
bytes and 62,682 evidence bytes, about 590.3 MB in total.

## Output

- `samples/nasa_pds_juno_junocam_perijove_rgb_framelets_u8/junocam_perijove_rgb_lossless_dn_u8/<PRODUCT_ID>.u8`
- `index/nasa_pds_juno_junocam_perijove_rgb_framelets_u8/samples.jsonl`: required fields
  plus shape, product ID, orbit, relative time, TDI, exposure, altitude, source MD5 and DN
  statistics.
- `filtered/nasa_pds_juno_junocam_perijove_rgb_framelets_u8/ingest_stats.json`: the
  exclusion record.

## Licence

NASA PDS mission data under the NASA SMD open scientific data policy (public, no
copyright). Cite the PDS data set `JUNO-J-JUNOCAM-2-EDR-L0-V1.0` and credit
NASA / JPL-Caltech / SwRI / MSSS.

## Caveats

- **Pixel-level decoding:** the IMG files are headerless IMAGE objects, so the emitted
  sample is byte-identical to the archived IMG. The decode is defined by the label
  (record 1, 1648-byte records, no prefix or suffix) and checked against `LINES`. The DN
  are the typed raster; nothing else is in the file.
- **Novelty risk:** windowed feature probes put both lossless and ICT JunoCam near the
  accepted `nasa_pds_voyager_iss_saturn_raw_u8` family (percentile distance about 0.05,
  medians over 3 x 256 KB windows per product). The production `zlsim gate`, which also
  needs at most 3% compression loss, decides.
- **Exposure settings vary:** TDI stages (1-6) and exposure (3.2-19.2 ms) vary between
  products. They are commanded settings of the same camera, companding and pipeline, not
  different regimes.
