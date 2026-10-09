# USGS 3DEP OR Harney-Silver 2020 Colorized Lidar (NV5 Geospatial, LAS 1.4 PDRF 7 LAZ): Native Per-Point RGB Colour Triplets UInt16

- Candidate id: `usgs_3dep_harneysilver2020_lidar_rgb_u16`
- Width: uint16
- Quantity: Per-point LAS Red, Green and Blue colour values (uint16, interleaved R,G,B per point, in file order), assigned to each lidar return from co-acquired imagery. The values are 8-bit colour MSB-aligned in the 16-bit LAS field (value = c*256).
- Source: https://rockyweb.usgs.gov/vdelivery/Datasets/Staged/Elevation/LPC/Projects/OR_HarneySilver_2020_A20/OR_HarneySilver_1_2020/
- Resources: https://rockyweb.usgs.gov/vdelivery/Datasets/Staged/Elevation/LPC/Projects/OR_HarneySilver_2020_A20/OR_HarneySilver_1_2020/LAZ/, https://rockyweb.usgs.gov/vdelivery/Datasets/Staged/Elevation/LPC/Projects/OR_HarneySilver_2020_A20/OR_HarneySilver_1_2020/LAZ/USGS_LPC_OR_HarneySilver_2020_A20_s16110w05820.laz
- License: US Public Domain (USGS 3DEP)
- License evidence: https://www.usgs.gov/information-policies-and-instructions/copyrights-and-credits
- License quote: USGS-authored or produced data and information are considered to be in the U.S. public domain. (Standard 3DEP LPC tile metadata accconst 'None.')
- Natural record: One LAZ tile: all points' (R,G,B) uint16 triplets interleaved in file point order, one sample per tile. Tiles hold 6.5-11.2 M points.
- Estimated samples: 12
- Estimated primary values: 324,000,000
- Estimated download bytes: 540,000,000
- Estimated primary bytes: 648,000,000
- Decode path: Use tools/laz/laszip.py (PDRF 7 is supported) to decode each tile and take the RGB fields (PDRF 7 byte offsets 30-35), writing them as interleaved little-endian uint16. Check that the header shows LAS 1.4, format 7, system 'NV5 Geospatial', and that RGB is not all zero.
- Novelty kind: new_quantity
- Measurement type: laser_range
- Instrument line: NV5 Geospatial airborne lidar colourized from co-acquired imagery (USGS 3DEP, LAS 1.4 PDRF 7)
- Archive collection: USGS 3DEP LPC rockyweb Staged Projects
- Novelty evidence: No lidar RGB family exists at any width locally, in the registry, ledger or downstream. Lidar at 16 bits is intensity only (DC 2015, IGN and NOAA in the pipeline), plus NCLT xyz. User priorities name RGB from point clouds as among the most likely new fields. novelty.py --url on the project matches only the generic rockyweb Projects path (different projects), and --terms HarneySilver/'lidar rgb' have no matches. Swisstopo RGB was avoided because its tiles are already used at 32 bits.
- Homogeneity: One project block (OR_HarneySilver_1_2020, 117 tiles), one vendor pipeline (all probed tiles: 'NV5 Geospatial', 'LasMonkey 2.6.3SP1', LAS 1.4 PDRF 7, scale 0.01), and one colourization convention (8-bit<<8). Take about 12 tiles spread across the block. Do not mix with sub-blocks 2-4 or other projects.
- Risks: Width honesty: the colour content is 8-bit MSB-aligned in the native 16-bit LAS field, so the low byte is always 0. There is precedent in the accepted tumvi_euroc_1024_cam_frames_u16 (12-bit MSB-aligned), but the judge may still call it hollow, so the builder must not rescale. Colours come from imagery, not the laser. Semi-arid sagebrush terrain may give a narrow colour range. rockyweb is slow, so use resumable downloads.
- Probe evidence: The LAZ listing has 117 tiles. Range GETs 0-4095 on tiles #5, #30, #70 and #100 returned 206 (totals 44,771,795, 26,745,077, 54,059,330 and 56,940,254 bytes). All show LAS 1.4, format 7, record length 36, 6.46-11.23 M points, sys 'NV5 Geospatial'. The first-point RGB values were (38400,40192,32768), (43520,39168,31232), (47616,47104,42752) and (44800,44032,41984), all multiples of 256. A survey of 90 colourized NOAA Digital Coast datasets found the same 8-bit<<8 convention everywhere real colour was present.

Proposed by the autocollect scout on 2026-10-08 (transcript `.data/pipeline/logs/scout_16bit/scout.20261008_225519.jsonl`).
