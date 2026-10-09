# USGS 3DEP OR Harney-Silver 2020 Colorized Lidar (NV5 Geospatial, LAS 1.4 PDRF 7 LAZ): Native 8-bit Per-Point RGB Colour Triplets UInt8

- Candidate id: `usgs_3dep_harneysilver2020_lidar_rgb_u8`
- Width: uint8
- Quantity: Per-point Red, Green and Blue colour of every lidar return (interleaved R,G,B per point in file order). The LAS RGB fields hold 8-bit colour MSB-aligned (value = c*256, low byte always 0), so the native 8-bit colour c = value>>8 is emitted.
- Source: https://rockyweb.usgs.gov/vdelivery/Datasets/Staged/Elevation/LPC/Projects/OR_HarneySilver_2020_A20/OR_HarneySilver_1_2020/
- Resources: https://rockyweb.usgs.gov/vdelivery/Datasets/Staged/Elevation/LPC/Projects/OR_HarneySilver_2020_A20/OR_HarneySilver_1_2020/LAZ/, https://rockyweb.usgs.gov/vdelivery/Datasets/Staged/Elevation/LPC/Projects/OR_HarneySilver_2020_A20/OR_HarneySilver_1_2020/LAZ/USGS_LPC_OR_HarneySilver_2020_A20_s16110w05820.laz
- License: US Public Domain (USGS 3DEP)
- License evidence: https://www.usgs.gov/information-policies-and-instructions/copyrights-and-credits
- License quote: USGS-authored or produced data and information are considered to be in the U.S. public domain.
- Natural record: One LAZ tile (1 of 117 in OR_HarneySilver_1_2020): all points' 8-bit (R,G,B) triplets interleaved in stored point order. Tiles hold about 6.5-11.2 M points (19-34 M values).
- Estimated samples: 12
- Estimated primary values: 320,000,000
- Estimated download bytes: 450,000,000
- Estimated primary bytes: 320,000,000
- Decode path: Decode each tile with tools/laz/laszip.py (LAS 1.4, PDRF 7, compressor 3 with RGB14; iter_chunks verified on a sparse head+tail copy of tile s16110w05820: chunk 0 = 50,000 points decoded). Read R,G,B at record offsets 30/32/34 (record length 36). Assert that (R|G|B)&0xFF == 0 for every point (the hollow-low-byte guard), then emit bytes (R>>8, G>>8, B>>8) per point. Validate the header (LAS 1.4, PDRF 7, 'NV5 Geospatial', 'LasMonkey 2.6.3SP1', scale 0.01) and the decoded point count.
- Novelty kind: new_quantity
- Measurement type: laser_range
- Instrument line: NV5 Geospatial airborne lidar colourised from co-acquired imagery (USGS 3DEP, LAS 1.4 PDRF 7)
- Archive collection: USGS 3DEP LPC rockyweb Staged Projects
- Novelty evidence: No lidar RGB family exists at any width (local, registry, ledger, downstream). The same material was screened out at 16 bits only because the 16-bit field is hollow (low byte always 0). At 8 bits it is exactly the native width, which removes that objection. novelty.py --terms HarneySilver/'lidar rgb'/colorized match only that 16-bit screening. The --url match is the generic rockyweb Projects path shared with other 3DEP projects (Cameron Peak, North Fork Payette, NC Geiger), not this project's files. Read-only zlsim feature probe: tile s16110w05820 chunk 0 nearest is Magellan F-MIDR at 0.035; tile #70 nearest is Magellan F-MIDR at 0.066 (Voyager 0.134, JunoCam/ISS candidates over 0.2).
- Homogeneity: One project block (OR_HarneySilver_1_2020, 117 tiles, 4.32 GB total), one vendor pipeline (NV5 Geospatial / LasMonkey 2.6.3SP1, LAS 1.4 PDRF 7) and one colourisation convention (8-bit<<8). Take about 12 tiles spread across the block. Do not mix sub-blocks 2-4 or other projects.
- Risks: Borderline breadth: one probe chunk sat 0.035 from Magellan SAR on features, another 0.066, so the median is uncertain and the compression test may decide. The colours are resampled from co-acquired imagery rather than measured by the laser (the screener's second objection at 16 bits); the defence is that this per-point colour stream in pulse order is the delivered LAS attribute. Semi-arid sagebrush gives a narrow colour range. rockyweb.usgs.gov rejects HEAD (use sizes from the directory listing) and has been flaky (proxy 503 once in the past), with no prd-tnm S3 mirror for this project, so use curl -C - with stall-based abort. Decoding is about 150 s per tile in pure Python.
- Probe evidence: Directory listing returned 200 with 117 .laz tiles and sizes (total 4,318,570,000 bytes). One-byte range GET with -L returned 206. A sparse copy (3 MB head + 1 MB tail range GETs) of s16110w05820 (44,771,795 bytes, 8,991,843 points) decoded chunk 0: low-byte OR = 0, RGB range 13056-55296, 163 distinct high bytes. Tile #70 (54,059,330 bytes) was decoded the same way for the feature probe.

Proposed by the autocollect scout on 2026-10-09 (transcript `.data/pipeline/logs/scout_8bit/scout.20261009_085042.jsonl`).
