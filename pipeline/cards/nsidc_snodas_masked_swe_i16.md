# NOAA NOHRSC SNODAS (NSIDC G02158) Daily 1-km CONUS Snow Water Equivalent Grids (Masked), Native Big-Endian Int16 mm

- Candidate id: `nsidc_snodas_masked_swe_i16`
- Width: int16
- Quantity: SNODAS modelled and assimilated snow water equivalent (product code 1034), in millimetres (meters/1000). The masked CONUS 6935x3351 grid uses native int16 with no-data -9999 outside CONUS land.
- Source: https://nsidc.org/data/g02158/versions/1
- Resources: https://noaadata.apps.nsidc.org/NOAA/G02158/masked/, https://noaadata.apps.nsidc.org/NOAA/G02158/masked/2020/02_Feb/SNODAS_20200201.tar
- License: LicenseRef-US-Government-Public-Domain (NOAA NWS NOHRSC product, archived by NOAA@NSIDC; citation requested)
- License evidence: https://nsidc.org/data/g02158/versions/1
- License quote: Producer NOAA NWS NOHRSC; NSIDC only archives. "As a condition of using these data, you must cite the use of this data set." Same host and licence basis as the accepted noaa_ims_snow_ice_cover_u8 (spdx LicenseRef-US-Government-Public-Domain, url noaa.gov open-data-dissemination).
- Natural record: One daily SWE grid = the us_ssmv11034tS__T0001TTNATS<date>05HP001.dat.gz member of that day's SNODAS tar: 23,239,185 values. Bounded scope is 16 mid-winter dates (1st of Dec, Jan, Feb, Mar for winters 2019/20-2022/23).
- Estimated samples: 16
- Estimated primary values: 371,826,960
- Estimated download bytes: 90,000,000
- Estimated primary bytes: 743,653,920
- Decode path: Fetch the daily tar from the anonymous HTTPS directory. Preferably walk the 512-byte ustar headers with small range GETs and range-fetch only the 1034 .dat.gz and .txt.gz members (about 5.3 MB per day); otherwise take the whole tar (about 25 MB). Use Python gzip and parse the .txt header (rows 3351, cols 6935, 2 bytes/pixel, no-data -9999, units meters/1000). Read the big-endian >h raster and emit little-endian int16 unchanged.
- Novelty kind: new_source
- Measurement type: snow_water_equivalent_grid
- Instrument line: NOAA NWS NOHRSC SNODAS snow data assimilation model, masked CONUS 1 km
- Archive collection: noaa_at_nsidc
- Novelty evidence: novelty.py --url noaadata.apps.nsidc.org/NOAA/G02158/masked/ --terms SNODAS 'snow water equivalent' NOHRSC: only same-host matches (noaa_ims_snow_ice_cover_u8, an 8-bit IMS snow/ice class map, a different product). No term matches in recipes, registry, ledger or downstream. --type snow_model_grid: 0. No snow-mass (SWE) quantity exists at any width.
- Homogeneity: One product (SWE 1034), one grid (masked CONUS 30-arcsec, dates after the 2013 header change), one unit (mm), one model system, one time of day (05Z). Snow depth, melt and other SNODAS products in the same tar are excluded and not to be proposed separately.
- Risks: (1) Value dominance: the probed 2020-02-01 grid is 48.4% -9999 no-data and 30.6% zero (no snow), with real SWE about 21%. This is native and below half, but the judge flags single-value dominance and must accept it as the native CONUS mask. (2) Large samples (46.5 MB each), so the count is low (16); keep under the 1 GB cap. (3) There is no explicit licence string on the NSIDC page; the argument rests on NOAA authorship and the accepted IMS precedent on the same host. (4) The NSIDC 'Basic' service level means paths could move; pin sizes and MD5s.
- Probe evidence: Directory listing of masked/2020/02_Feb is live (SNODAS_20200201.tar 25,610,240 B); the unmasked tree is also live. Walked tar headers with 512-byte range GETs: 16 members, SWE member us_ssmv11034tS__T0001TTNATS2020020105HP001.dat.gz 5,282,204 B at offset 17,683,456+512. Range-fetched the SWE .dat.gz and .txt.gz: header gives 6935 cols x 3351 rows, integer, 2 bytes/pixel, no-data -9999, meters/1000. Decoded 23,239,185 >h values: 2,254 distinct, -9999 48.4%, 0 30.6%, max 32767.

Proposed by the autocollect scout on 2026-10-14 (transcript `.data/pipeline/logs/scout_16bit/scout.20261014_132438.jsonl`).
