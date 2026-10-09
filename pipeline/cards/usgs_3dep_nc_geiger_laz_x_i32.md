# USGS 3DEP NC Phase 4 Central-West Geiger-Mode Lidar (Harris IntelliEarth GmAPD, 2016) Per-Tile LAS Scaled Int32 X Record Coordinates

- Candidate id: `usgs_3dep_nc_geiger_laz_x_i32`
- Width: int32
- Quantity: LAS point-record X field: native little-endian int32 easting code (scale 0.01 US survey ft, offset 0, NC State Plane), one value per lidar return in file order
- Source: https://prd-tnm.s3.amazonaws.com/StagedProducts/Elevation/LPC/Projects/NC_Phase_4_CentralWestNC_GEIGER_A16/NC_Phase4_Anson_2016/
- Resources: https://prd-tnm.s3.amazonaws.com/StagedProducts/Elevation/LPC/Projects/NC_Phase_4_CentralWestNC_GEIGER_A16/NC_Phase4_Anson_2016/NC_Phase4_Anson_2016.vpc, https://prd-tnm.s3.amazonaws.com/StagedProducts/Elevation/LPC/Projects/NC_Phase_4_CentralWestNC_GEIGER_A16/NC_Phase4_Anson_2016/0_file_download_links.txt, https://rockyweb.usgs.gov/vdelivery/Datasets/Staged/Elevation/LPC/Projects/NC_Phase_4_CentralWestNC_GEIGER_A16/NC_Phase4_Anson_2016/LAZ/USGS_LPC_NC_Phase_4_CentralWestNC_GEIGER_A16_10643117.laz
- License: US public domain (USGS 3DEP federal data, no use restrictions)
- License evidence: https://prd-tnm.s3.amazonaws.com/StagedProducts/Elevation/LPC/Projects/NC_Phase_4_CentralWestNC_GEIGER_A16/NC_Phase4_Anson_2016/metadata/USGS_LPC_NC_Phase_4_CentralWestNC_GEIGER_A16_10630806.xml
- License quote: Per-tile FGDC metadata: origin 'U.S. Geological Survey'; accconst 'None.'; useconst 'Acknowledgement of the originating agencies would be appreciated...'. USGS policy (usgs.gov/information-policies-and-instructions/copyrights-and-credits): USGS-authored or produced data are considered to be in the U.S. public domain.
- Natural record: One LAZ tile (one USGS_LPC_..._<tileid>.laz file) = one sample: the full X column of every point record in that tile, in file order
- Estimated samples: 24
- Estimated primary values: 90,000,000
- Estimated download bytes: 700,000,000
- Estimated primary bytes: 360,000,000
- Decode path: curl the tiles from rockyweb with retries (TLS there is flaky, see risks). Decode each with the repo's pure-stdlib tools/laz/laszip.py (iter_chunks; LAS 1.4, point format 6, LASzip layered compressor). Take X as the first int32 of every 30-byte record and write it as little-endian int32. Pick tiles from the project VPC (STAC FeatureCollection with pc:count per tile): the Anson County tiles with pc:count between about 2M and 6M (74 tiles fall between 2M and 10M), sorted by tile id, first ~24. This keeps the decode near 25 min at about 60k points/s.
- Novelty kind: new_source
- Measurement type: laser_range
- Instrument line: harris_intelliearth_geiger_mode_lidar
- Archive collection: prd-tnm.s3.amazonaws.com/StagedProducts/Elevation/LPC (USGS 3DEP)
- Novelty evidence: novelty.py --url for the rockyweb/prd-tnm GEIGER project path: no URL matches. Lidar term matches are only the DC LiDAR 2015 families (u8 class, u16 intensity, f64 GPS time), GOOSE VLS-128 f32 sensor-frame xyz, NCLT u16 and OLA f64. The corpus has no scaled-int32 LAS record coordinates at any width, and no Geiger-mode (single-photon-sensitive APD array) lidar. The earlier usgs_3dep_las_intensity_u16 registry row was superseded for intensity only; it does not cover coordinates or this project.
- Homogeneity: One project, one county sub-block (NC_Phase4_Anson_2016), one sensor (sysid 'IntelliEarthGmAPDSensorS/N003'), one processing chain (ESP ANALYST + LAStools laszip). All tiles share scale 0.01, offset 0, the same CRS and point format 6. Only the X field, so one unit and tick lattice.
- Risks: rockyweb.usgs.gov TLS handshakes intermittently fail (SSL_ERROR_ZERO_RETURN); 2 of 4 range GETs succeeded only on retry, so download.sh needs curl --retry plus an outer retry loop. Full interior tiles have 17-31M points (191 MB), so the builder must keep to the smaller-count tiles to bound decode time and stay under 1 GB of primary output. Selecting by pc:count favours partial edge tiles. Within a tile the upper byte of X is nearly constant (values about 1.63e8), which is native and expected. A Y family from the same files would not be a new family, so propose only X here. The byte gate could still find similarity to other coordinate streams.
- Probe evidence: Range GET bytes 0-8191 of ..._10643117.laz returned 206: LAS 1.4, pf6, n=25,349,773, scale 0.01, offset (0,0,0), X 1,630,000.00-1,632,500.00 ft (stored int32 about 163,000,000-163,250,000, 28 bits), LASzip VLR present. HEAD gives content-length 191,261,809. The VPC (9.1 MB) lists 2,533 Anson tiles with pc:count from 0.67M to 30.8M, 74 of them between 2M and 10M. 0_file_download_links.txt has 2,533 rockyweb URLs.

Proposed by the autocollect scout on 2026-10-08 (transcript `.data/pipeline/logs/scout_32bit/scout.20261008_211441.jsonl`).
