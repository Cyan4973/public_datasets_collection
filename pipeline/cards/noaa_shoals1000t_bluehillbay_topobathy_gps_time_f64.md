# NOAA/MCP 2017 Blue Hill Bay ME Topobathy Lidar, SHOALS-1000T Sensor (Digital Coast ID 8526): Native Per-Point GPS Time Float64

- Candidate id: `noaa_shoals1000t_bluehillbay_topobathy_gps_time_f64`
- Width: float64
- Quantity: Per-point acquisition GPS time (adjusted standard GPS seconds, ~1.833e8 s), LAS 1.4 PDRF 6 field gps_time, copied as stored, in file record order. Sensor is the Fugro SHOALS-1000T airborne bathymetric lidar at a 2.5 kHz pulse repetition rate, roughly 200x slower than conventional topographic scanners, so inter-point time deltas and duplicate structure differ from DC LiDAR 2015
- Source: https://noaa-nos-coastal-lidar-pds.s3.amazonaws.com/laz/geoid18/8526/index.html
- Resources: https://noaa-nos-coastal-lidar-pds.s3.amazonaws.com/?list-type=2&prefix=laz/geoid18/8526/, https://noaa-nos-coastal-lidar-pds.s3.amazonaws.com/laz/geoid18/8526/stac/noaa_copc_item_collection_m8526.json, https://noaa-nos-coastal-lidar-pds.s3.amazonaws.com/laz/geoid18/8526/metadata_me2017_blue_hill_bay_shoals.xml, https://noaa-nos-coastal-lidar-pds.s3.amazonaws.com/laz/geoid18/8526/20170705_tile_537000_4902000.copc.laz
- License: NOAA Open Data Dissemination (NODD) open data; US Government work (attribution requested)
- License evidence: https://registry.opendata.aws/noaa-coastal-lidar/
- License quote: NOAA data disseminated through NODD are open to the public and can be used as desired. ... NOAA requests attribution for the use or dissemination of unaltered NOAA data.
- Natural record: One COPC LAZ tile (one survey-day tile file, e.g. 20170705_tile_537000_4902000.copc.laz) = one sample: the gps_time field of every point record in stored order
- Estimated samples: 92
- Estimated primary values: 25,298,628
- Estimated download bytes: 113,122,575
- Estimated primary bytes: 202,389,024
- Decode path: curl the 92 .copc.laz objects (S3 listing gives exact keys and sizes). Decode with the repo's tools/laz/laszip.py: compressor 3 layered chunks, POINT14 v3 item (10,30,3), variable chunks as in COPC. Take the 8 bytes at offset 22 of each 30-byte PDRF-6 record as little-endian float64. Pure stdlib
- Novelty kind: new_source
- Measurement type: laser_range
- Instrument line: fugro_shoals_1000t_bathymetric_lidar
- Archive collection: noaa-nos-coastal-lidar-pds/laz/geoid18/8526
- Novelty evidence: The only local LAS GPS-time family is dc_lidar_2015_gps_time_f64: DC bucket, uncompressed LAS, a conventional topographic scanner in acquisition order. Here the sensor regime is different: a 2.5 kHz SHOALS bathymetric lidar (metadata: 'collects bathymetric LiDAR data at 2.5 kHz Pulse Repetition Rate ... 0.15 pts/m2'), single returns, COPC octree record order, different epoch (~1.833e8 vs ~1.1e8 s). novelty.py --url on the 8526 prefix: no local, registry or downstream hit for the bucket. Ledger NOAA hits are other projects at other widths (8727 Potomac u16, 10423 Coastal Maine u8), not this dataset. This is the whole published population of the SHOALS-sensor project
- Homogeneity: One project, one sensor (SHOALS-1000T only; the concurrent Riegl VQ-820-G data is a separate dataset, 8525, and is excluded), one survey season (2017-06/07), one LAS layout (1.4 PDRF 6, adjusted-standard GPS time, global_encoding 17), one quantity in seconds. Samples range from 468 to 978,629 points (median 255,850); 1 tile is under 1,000 points
- Risks: COPC files store points in octree node order, not strict acquisition order, so the stream is piecewise monotone with jumps (it is still the native stored record order). Sample sizes are uneven, with a few tiny tiles; the builder may drop the one tile under 1,000 points or keep it with a note. The byte gate could still find it close to DC GPS time, though the 200x slower pulse rate and COPC ordering should separate it. The STAC items carry an odd 'license: CC-BY-1.0' tag; the authoritative NODD terms are more permissive
- Probe evidence: Range GET of header and VLRs (65 KB) on 20170705_tile_537000_4902000.copc.laz: LAS1.4 pf=6 rl=30 npts=142353 ge=17 (adjusted standard), laszip compr=3 items=[(10,30,3)], COPC info gpstime 183310362.87 to 183312079.54. The first raw point's gps_time, read with an 80-byte range, is 183310363.391. The S3 listing shows 92 .copc.laz files totalling 113,122,575 bytes. The STAC item collection (2.95 MB) gives pc:count summing to 25,298,628 and per-tile GpsTime statistics. The metadata XML confirms the SHOALS-1000T at 2.5 kHz

Proposed by the autocollect scout on 2026-10-08 (transcript `.data/pipeline/logs/scout_64bit/scout.20261008_211441.jsonl`).
