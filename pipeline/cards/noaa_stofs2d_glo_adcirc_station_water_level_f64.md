# NOAA STOFS-2D-Global (ADCIRC) Forecast-Cycle Station Water-Surface Elevation Time Series (fort.61, v2.1.0) Float64

- Candidate id: `noaa_stofs2d_glo_adcirc_station_water_level_f64`
- Width: float64
- Quantity: ADCIRC-simulated water-surface elevation above geoid [m] (tide + storm surge) at 1,688 output stations for the full -6 h nowcast plus +180 h forecast of one STOFS-2D-Global cycle. Native NetCDF4 f8 variable 'zeta' (time=1260, station=1688), fill -99999.0 for dry stations.
- Source: https://registry.opendata.aws/noaa-gestofs/
- Resources: https://noaa-gestofs-pds.s3.amazonaws.com/stofs_2d_glo.20250601/00/rerun/stofs_2d_glo_fcst.61.nc, https://noaa-gestofs-pds.s3.amazonaws.com/?list-type=2&delimiter=/&prefix=stofs_2d_glo, https://noaa-gestofs-pds.s3.amazonaws.com/README.html
- License: NOAA open data (NODD; public, no restrictions; attribution requested)
- License evidence: https://registry.opendata.aws/noaa-gestofs/
- License quote: NOAA data disseminated through NODD are open to the public and can be used as desired. ... NOAA requests attribution for the use or dissemination of unaltered NOAA data.
- Natural record: One forecast cycle's stofs_2d_glo_fcst.61.nc (about 15.8 MB): the whole zeta matrix (1260 x 1688 = 2,126,880 doubles) is one sample. Suggested bounded subset: the 00z cycle on about 24 dates spread over the homogeneous v2.1.0 window (about 2024-06..2025-10; file size changed between 2024-01 (12.07 MB) and 2024-06 (15.82 MB), and by 2026-09 the product had become points.cwl.nc).
- Estimated samples: 24
- Estimated primary values: 51,045,120
- Estimated download bytes: 380,000,000
- Estimated primary bytes: 408,360,960
- Decode path: NetCDF4/HDF5 with the repo's pure-stdlib reader (h5lite parsed this file's root links, dataspace, datatype and chunked layout). zeta is chunked (1,1688) with a v1 B-tree chunk index (TREE type 1) and filters shuffle(2) + deflate(1). Per chunk: zlib.decompress, byte-unshuffle with element size 8, struct '<1688d'. Pin the 'version' global attribute (noaa.stofs.2d.glo.v2.1.0...) and station count 1688 in download.sh validation.
- Novelty kind: new_source
- Novelty evidence: novelty.py --url https://noaa-gestofs-pds.s3.amazonaws.com/ --terms stofs adcirc 'storm surge' found nothing anywhere: no recipes, registry, ledger or downstream. Honest caveat: local 64-bit has observed water levels (noaa_coops_water_level, noaa_tides_water_level: gauge observations, decimal-quantized). STOFS is a different generation process (an unstructured-mesh hydrodynamic simulation with full-mantissa doubles), so this is a new source and process for the same physical quantity, not a new modality.
- Homogeneity: One model (ADCIRC, STOFS-2D-Global v2.1.0, OceanMesh2D grid), one product (fcst.61 station elevation), one unit (m above geoid), fixed 1,688-station set and 1,260-step lattice. Use only the 00z cycle and the v2.1.0 window to avoid station-set or version changes. Keep the native -99999.0 dry-node fill under an explicit policy, or drop always-dry stations consistently.
- Risks: Same physical quantity as existing observed water-level families, so a judge may rate novelty as content-same-modality. Lowest priority of this set. Consecutive cycles overlap in forecast time, so spread dates. A few inland stations reach ~118 m above geoid, so verify ranges. Shuffle+deflate chunk decode must be self-tested. The 'rerun' path segment should be pinned as listed.
- Probe evidence: S3 listing: stofs_2d_glo.YYYYMMDD/{00,06,12,18}/rerun/stofs_2d_glo_fcst.61.nc about 15.8 MB, present 2023-06-01 through 2025-10-01 (HEAD sizes 12.08 MB for 2023-06/2024-01 and 15.8 MB for 2024-06..2025-10). Range GET of 128 KB, parsed: zeta (1260,1688) f8 chunked (1,1688) filters [shuffle, deflate]; x, y (1688,) f8; time (1260,) f8; attributes long_name 'water surface elevation above geoid', units m, _FillValue -99999.0; global version 'noaa.stofs.2d.glo.v2.1.0r1.v55.12', model ADCIRC. Fetched one TREE node (57 chunk entries) and one 12,388-byte chunk; inflate+unshuffle gave 1688 doubles, 2 fill, range -3.19..118.17 m, e.g. 2.602268942963752, all full precision.

Proposed by the autocollect scout on 2026-10-05 (transcript `.data/pipeline/logs/scout_64bit/scout.20261005_231243.jsonl`).
