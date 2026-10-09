# IGN LiDAR HD (France) Classified COPC Tiles, Block 21LHD2GO, Leica TerrainMapper:90560: Native Per-Point Return Intensity UInt16

- Candidate id: `ign_lidarhd_terrainmapper_intensity_u16`
- Width: uint16
- Quantity: LAS 1.4 point-format-6 per-point laser return intensity (uint16, record offset 12), one sensor (Leica TerrainMapper serial 90560), one acquisition block (mission 21LHD2GO, flown 2023-08-09/17, classified with IGN_AUTO_V5)
- Source: https://www.data.gouv.fr/datasets/nuages-de-points-lidar-hd
- Resources: https://data.geopf.fr/wfs/ows?SERVICE=WFS&VERSION=2.0.0&REQUEST=GetFeature&TYPENAMES=IGNF_LIDAR-HD_METADONNEE:metadata&OUTPUTFORMAT=application/json&CQL_FILTER=code_mission='21LHD2GO', https://data.geopf.fr/telechargement/download/LiDARHD-NUALID/NUALHD_1-0__LAZ_LAMB93_GO_2025-09-22/LHD_FXX_0473_6368_PTS_LAMB93_IGN69.copc.laz, https://data.geopf.fr/telechargement/download/LiDARHD-NUALID/NUALHD_1-0__LAZ_LAMB93_GO_2025-09-22/LHD_FXX_0483_6355_PTS_LAMB93_IGN69.copc.laz
- License: Licence Ouverte / Open Licence 2.0 (Etalab-2.0)
- License evidence: https://www.data.gouv.fr/api/1/datasets/nuages-de-points-lidar-hd/
- License quote: data.gouv.fr dataset 'Nuages de points LiDAR HD' (organization: Institut national de l'information géographique et forestière) carries license id 'lov2' = 'Licence Ouverte / Open Licence version 2.0' (flags okd_compliant, domain_data).
- Natural record: One 1 km x 1 km COPC LAZ tile = one sample: the tile's full intensity stream in file (COPC octree) order
- Estimated samples: 6
- Estimated primary values: 110,000,000
- Estimated download bytes: 750,000,000
- Estimated primary bytes: 220,000,000
- Decode path: curl the pinned tile URLs (Range supported, HEAD gives content-length e.g. 161,276,616 B for 0473_6368). Python: tools/laz/laszip.py iter_chunks (COPC = LAS 1.4 PDRF 6, rl 30, compressor 3 layered chunks, variable chunk sizes, 'lazperf variant' VLR); take '<H' at record offset 12 via array slicing; write little-endian uint16 .bin per tile. Verified: first COPC chunks of tile 0473_6368 decode cleanly (152k points). Tile selection: WFS metadata layer filtered by code_mission='21LHD2GO' AND capteur='["Leica TerrainMapper:90560"]' (2,500 tiles in mission; 375 of 400 sampled were this sensor); pick ~6 tiles with 15-20M points (nombre_points property) to keep download ~750 MB and decode ~30 min at ~60-70k pts/s.
- Novelty kind: new_source
- Measurement type: laser_range
- Instrument line: Leica TerrainMapper airborne lidar (serial 90560), IGN LiDAR HD program
- Archive collection: IGN Géoplateforme data.geopf.fr LiDARHD-NUALID
- Novelty evidence: novelty.py --url data.geopf.fr/telechargement/download/LiDARHD-NUALID/ --terms lidar geopf: no URL/term matches in recipes, registry, ledger or downstream. Only LAS intensity family is dc_lidar_2015_intensity_u16 whose realized range is 0..255 with 95 distinct values (6.2 bits entropy, effectively 8-bit). Probe of this tile: intensity 300..7442, 4,622 distinct values in 152k points, order-0 entropy 11.8 bits — a genuinely 13-bit radiometric stream from a different sensor (Leica TerrainMapper, 2023) and national program (France).
- Homogeneity: One program (IGN LiDAR HD), one acquisition mission (21LHD2GO), one sensor serial (Leica TerrainMapper:90560), one classification process, one delivery (NUALHD_1-0 GO 2025-09-22). Do NOT mix missions/sensors (the WFS lists RIEGL VQ-780 II-S and Leica CityMapper-2 tiles elsewhere; a coastal RIEGL edge tile showed intensity 1..16 — a different regime).
- Risks: Tiles are large (~100-160 MB, 15-30M points) so decode time is the main cost (~4-7 min/tile). COPC point order is octree-node order, not acquisition order (still the file's native order). data.geopf.fr download host has delivery-date-versioned paths (NUALHD_1-0__LAZ_LAMB93_GO_2025-09-22) that could be re-issued; pin size+sha256 and discover via WFS url_npl. Sample count is ~6 large natural samples (fine per collect-not-prepare; could go to 8-10 if byte cap allows). Byte gate vs dc_lidar intensity should pass given range/entropy difference, but other intensity families in this round may land near each other.
- Probe evidence: WFS GetFeature on IGNF_LIDAR-HD_METADONNEE:metadata returned 524,687 tiles total, 2,500 for 21LHD2GO, with properties capteur, nombre_points, url_npl. HEAD on LHD_FXX_0473_6368 COPC: HTTP/2 200, content-length 161276616, accept-ranges bytes. Header: LAS 1.4, PDRF 6, rl 30, 25,081,499 points, VLRs copc/laszip encoded (lazperf variant)/LASF_Projection. Decoded 6 MB prefix (EVLR count patched in scratch copy): 152,015 points, intensity 300..7442, 4,622 distinct, H=11.78 bits; point source ids 15/16 (flight lines).

Proposed by the autocollect scout on 2026-10-08 (transcript `.data/pipeline/logs/scout_16bit/scout.20261008_211441.jsonl`).
