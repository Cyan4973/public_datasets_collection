# NOAA/IHO DCDB Crowdsourced Bathymetry Vessel Track Coordinates Float64

- Candidate id: `noaa_dcdb_csb_vessel_track_lonlat_f64`
- Width: float64
- Quantity: WGS84 longitude and latitude (decimal degrees, 5-6+ decimals) of vessel GNSS fixes logged with each echo-sounder sounding during routine maritime operations. Emitted as (LON, LAT) interleaved per row in file order. Longitudes such as -124.100532 need more significant digits than float32 holds.
- Source: https://noaa-dcdb-bathymetry-pds.s3.amazonaws.com/docs/readme.html
- Resources: https://noaa-dcdb-bathymetry-pds.s3.amazonaws.com/?list-type=2&prefix=csb/csv/2024/06/, https://noaa-dcdb-bathymetry-pds.s3.amazonaws.com/docs/FAQ.html, https://noaa-dcdb-bathymetry-pds.s3.amazonaws.com/csb/csv/2024/06/01/20240601000613980503_061e2f30-c234-4cf0-b880-42bb03ab857d_pointData.csv
- License: Unrestricted public data (NOAA NCEI-hosted IHO DCDB, NOAA Open Data Dissemination)
- License evidence: https://noaa-dcdb-bathymetry-pds.s3.amazonaws.com/docs/FAQ.html
- License quote: "The DCDB archives and shares, freely and without restrictions, depth data contributed by mariners. It is hosted by the U.S. National Oceanographic and Atmospheric Administration (NOAA) on behalf of the IHO Member States."
- Natural record: One CSB submission file (<timestamp>_<uuid>_pointData.csv) delivered by a trusted node for one platform/trip, with columns UNIQUE_ID,FILE_UUID,LON,LAT,DEPTH,TIME,PLATFORM_NAME,PROVIDER. The sample is its LON/LAT pairs.
- Estimated samples: 2,300
- Estimated primary values: 14,800,000
- Estimated download bytes: 1,410,000,000
- Estimated primary bytes: 119,000,000
- Decode path: 1. curl the S3 ListObjectsV2 pages for a pinned date window (suggest 2024-06-01..2024-06-07) and record keys and sizes. 2. curl each CSV. 3. Parse with the Python csv module: float(LON), float(LAT) give IEEE f64, packed with struct '<d'. Reject rows outside [-180,180]/[-90,90] or non-finite. 4. Write one sample per file; DEPTH, TIME and IDs are not primary.
- Novelty kind: new_source
- Novelty evidence: `novelty.py --url https://noaa-dcdb-bathymetry-pds.s3.amazonaws.com/ --terms dcdb bathymetry crowdsourced` returns no matches anywhere. The only vessel-track family is noaa_marinecadastre_ais_2024_01_01_f32 / noaa_ais_f32: 32-bit, a different source (MarineCadastre AIS), not this file set. 64-bit coordinate families exist (citibike, gbif, gtfs shapes, natural earth), so this is a new source within a known modality.
- Homogeneity: One quantity (geodetic lon/lat in decimal degrees) under one regime. Trusted nodes log at different cadences (Rosepoint about 1/min, PGS, AquaMap), but the unit, scale and meaning are identical. DEPTH is excluded because its precision is provider-dependent (integers for some, float32-widened for AquaMap).
- Risks: 1. Thin extraction ratio: about 8% of CSV bytes are kept (~1.4 GB download for ~120 MB), tolerable only because the absolute kept signal is large. 2. A judge may rate the novelty low, since coordinates are already well represented at 64-bit. 3. Files range from 229 B to 5.4 MB (June 2024 median 201,131 B ≈ 1,000 rows ≈ 2,000 values). Tiny files should be kept, not filtered, and the median still clears the floor. 4. Mixed decimal precision across providers (5-6 decimals; some float noise like 27.462299999999995). 5. A date-window subset must be justified as a size cap; one full month is 6.06 GB.
- Probe evidence: Bucket list OK (prefixes csb/, docs/, mb/; csb/csv/2017..2026). Read docs/readme.html (column schema) and docs/FAQ.html (license quote). Paginated listing of csb/csv/2024/06/: 9,904 files, 6,056,674,119 bytes, median 201,131 B, p25 152,729 B, 71 distinct submitter UUIDs in the first 1,000 keys. Range-GET heads of 8 files from different providers show LON/LAT rows such as -76.77503,35.381575 (Rosepoint), -21.99098,22.762359 (PGS), -124.100532,46.906053.

Proposed by the autocollect scout on 2026-10-05 (transcript `.data/pipeline/logs/scout_64bit/scout.20261005_174424.jsonl`).
