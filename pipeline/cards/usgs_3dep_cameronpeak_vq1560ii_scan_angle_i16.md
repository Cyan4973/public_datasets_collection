# USGS 3DEP CO Cameron Peak Wildfire 2021 Lidar (Riegl VQ-1560 II, LAS 1.4 PDRF 6 LAZ): Native Per-Point Scan Angle Int16 (0.006° units)

- Candidate id: `usgs_3dep_cameronpeak_vq1560ii_scan_angle_i16`
- Width: int16
- Quantity: Per-point LAS 1.4 extended scan angle (signed int16, 0.006 degree increments, roughly ±5000), in file point order
- Source: https://rockyweb.usgs.gov/vdelivery/Datasets/Staged/Elevation/LPC/Projects/CO_CameronPeakWildfire_2021_D21/CO_CameronPkFire_1_2021/
- Resources: https://rockyweb.usgs.gov/vdelivery/Datasets/Staged/Elevation/LPC/Projects/CO_CameronPeakWildfire_2021_D21/CO_CameronPkFire_1_2021/LAZ/, https://rockyweb.usgs.gov/vdelivery/Datasets/Staged/Elevation/LPC/Projects/CO_CameronPeakWildfire_2021_D21/CO_CameronPkFire_1_2021/LAZ/USGS_LPC_CO_CameronPeakWildfire_2021_D21_w2945n1475.laz, https://rockyweb.usgs.gov/vdelivery/Datasets/Staged/Elevation/LPC/Projects/CO_CameronPeakWildfire_2021_D21/CO_CameronPkFire_1_2021/metadata/
- License: US Public Domain (USGS 3DEP)
- License evidence: https://www.usgs.gov/information-policies-and-instructions/copyrights-and-credits
- License quote: USGS-authored or produced data and information are considered to be in the U.S. public domain. Tile metadata useconst: 'Acknowledgement of the originating agencies would be appreciated in products derived from these data.' accconst: 'None.'
- Natural record: One LAZ tile (one sample per tile): all points' scan-angle values in file order. Tiles hold 7.5-12 M points.
- Estimated samples: 12
- Estimated primary values: 120,000,000
- Estimated download bytes: 900,000,000
- Estimated primary bytes: 240,000,000
- Decode path: Use tools/laz/laszip.py (pure stdlib; supports LAS 1.4 PDRF 6 layered chunks) to decode each pinned tile, then extract the int16 scan_angle field (PDRF 6 byte offset 18) to a little-endian int16 array. Download with curl -C - and --speed-limit; check the header (version 1.4, format 6, system id 'Riegl VQ-1560 II', point count) and the pinned size.
- Novelty kind: new_quantity
- Measurement type: laser_range
- Instrument line: Riegl VQ-1560 II airborne lidar (USGS 3DEP, LAS 1.4 PDRF 6)
- Archive collection: USGS 3DEP LPC rockyweb Staged Projects
- Novelty evidence: No 16-bit scan-angle family exists anywhere. The only scan-angle family is srsp_scotland_phase1_lidar_scan_angle_i8, at 8 bits (whole-degree rank from PDRF 1 and a different sensor). Pipeline lidar at 16 bits is intensity only (IGN, NOAA 8727; NRCan screened out). novelty.py --url on this project matches only the generic rockyweb Projects path, shared with usgs_3dep_nc_geiger_laz_x_i32 and usgs_3dep_id_northforkpayette_laz_return_number_u8, which are different projects and files. The fine-grained 0.006° angle follows the scanner geometry (per-scan-line ramps, dual-channel interleave) and differs from the intensity, coordinate and classification streams.
- Homogeneity: One project, one sensor (all probed tiles report system id 'Riegl VQ-1560 II', generator 'GeoCue LAS Updater', LAS 1.4 PDRF 6, scale 0.001), and one unit. 1,167 tiles are available (55-92 MB each). Take about 12 tiles spread across the project, one sample per tile.
- Risks: rockyweb.usgs.gov is slow and directory listings sometimes time out; download.sh needs resumable curl and retries. The extraction ratio is poor (2 of 30 bytes per point, about 900 MB downloaded for about 240 MB kept), tolerable because the kept signal is large and no leaner source exists. Pure-Python decode at about 60k pts/s takes about 3 min per tile (about 35-40 min total). Tiles may be sorted spatially rather than in acquisition order, which would weaken the sawtooth structure but the data stays genuine.
- Probe evidence: The LAZ directory listing has 1,167 .laz files. Range GETs 0-4095 on tiles #100, #583 and #1000 returned 206 with Content-Range totals 83,924,010, 92,486,658 and 55,108,988 bytes. The headers show LAS 1.4, format 6 (LAZ), record length 30, 9.27 M, 11.90 M and 7.57 M points, sys 'Riegl VQ-1560 II'. The first raw points have scan_angle 1455, -3920 and 4479 (in 0.006° units). The tile metadata XML gives accconst 'None.'

Proposed by the autocollect scout on 2026-10-08 (transcript `.data/pipeline/logs/scout_16bit/scout.20261008_225519.jsonl`).
