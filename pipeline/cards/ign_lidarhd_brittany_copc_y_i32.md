# IGN LiDAR HD (France national programme) Block AE (Finistère) COPC Point Clouds: LAS Scaled Int32 Y Record Coordinates

- Candidate id: `ign_lidarhd_brittany_copc_y_i32`
- Width: int32
- Quantity: LAS point-record Y field: native little-endian int32 northing code (scale 0.01 m, offset 0, Lambert-93), one value per return in COPC file order
- Source: https://data.geopf.fr/telechargement/resource/LiDARHD-NUALID/NUALHD_1-0__LAZ_LAMB93_AE_2025-07-22
- Resources: https://data.geopf.fr/telechargement/resource/LiDARHD-NUALID/NUALHD_1-0__LAZ_LAMB93_AE_2025-07-22?limit=50&page=1, https://data.geopf.fr/telechargement/download/LiDARHD-NUALID/NUALHD_1-0__LAZ_LAMB93_AE_2025-07-22/LHD_FXX_0098_6848_PTS_LAMB93_IGN69.copc.laz
- License: Licence Ouverte / Open Licence (Etalab 2.0)
- License evidence: https://data.geopf.fr/csw?service=CSW&version=2.0.2&request=GetRecordById&id=IGNF_NUAGES-DE-POINTS-LIDAR-HD&outputSchema=http://www.isotc211.org/2005/gmd&elementSetName=full
- License quote: Licence Ouverte / Open License (compatible ODC-BY, CC-BY 2.0) - ISO metadata of IGNF_NUAGES-DE-POINTS-LIDAR-HD: 'issue de l'acquisition réalisée dans cadre du programme national LiDAR HD (exclusivement) avec une densité d'au moins 10 impulsions au m²'
- Natural record: One 1 km2 LiDAR HD dalle (LHD_FXX_<x>_<y>_PTS_LAMB93_IGN69.copc.laz) = one sample: the full Y column in file order
- Estimated samples: 12
- Estimated primary values: 80,000,000
- Estimated download bytes: 500,000,000
- Estimated primary bytes: 320,000,000
- Decode path: Page the Atom feed for block AE (2,213 entries; each link carries gpf_dl:length). Pick ~12 dalles with length 25-60 MB (about 4-10M points at about 6 B/point) in sorted name order. curl them and decode with tools/laz/laszip.py (COPC = LAS 1.4 pf6, layered compressor 3 with variable chunks, which the tool supports). Y is the int32 at record offset 4 of each 30-byte record; emit little-endian int32.
- Novelty kind: new_source
- Measurement type: laser_range
- Instrument line: ign_lidar_hd_airborne_lidar
- Archive collection: data.geopf.fr/telechargement (IGN Géoplateforme)
- Novelty evidence: novelty.py --url data.geopf.fr LiDARHD-NUALID with terms lidarhd/ign/geopf: no matches in any layer. No IGN/Géoplateforme source in the corpus and no int32 LAS coordinates. COPC octree point order gives different sequence statistics from the scanline-ordered tiles of the other candidates.
- Homogeneity: One national programme, one production block (AE, published 2025-07-22), one producer pipeline (PDAL 2.8.2 COPC writer), fixed scale 0.01 and offset 0, one CRS (Lambert-93/IGN69). Only Y.
- Risks: Inland dalles are heavy (50-200 MB, 10-40M points) and laszip.py runs at about 60k points/s, so the recipe should restrict itself to 25-60 MB dalles, which leans toward coastal and partly-sea tiles. COPC reorders points into octree nodes (this is the published file order, not acquisition order). It is the weakest of the four: a second Y family, after the NZ one, so the byte gate may find it close if COPC ordering does not separate it. The feed has some near-empty dalles (KB-sized) that the size filter must exclude.
- Probe evidence: Range GET bytes 0-8191 of LHD_FXX_0098_6848_PTS_LAMB93_IGN69.copc.laz returned 206: LAS 1.4, sys 'PDAL', pf6, n=2,333,484, scale 0.01, offset (0,0,0), Y 6,847,000-6,848,000 m, so stored Y is about 684,700,000 (30 bits); COPC info VLR and LASzip VLR present. The block AE Atom feed reports totalentries=2213. Sampled lengths range from 60 KB to 198 MB, with many dalles at 28-60 MB.

Proposed by the autocollect scout on 2026-10-08 (transcript `.data/pipeline/logs/scout_32bit/scout.20261008_211441.jsonl`).
