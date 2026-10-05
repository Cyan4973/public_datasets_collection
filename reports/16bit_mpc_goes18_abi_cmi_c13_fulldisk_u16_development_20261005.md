# GOES-18 ABI CMI band-13 full-disk brightness-temperature uint16 development

## Outcome

Accepted `mpc_goes18_abi_cmi_c13_fulldisk_u16`: twelve complete GOES-18 (GOES-West) Advanced Baseline Imager L2 Cloud and Moisture Imagery band-13 full-disk scans. Band 13 is the 10.3 µm clean longwave IR window. Values are the native packed 12-bit uint16 codes of NOAA's `CMI_C13` variable.

This is the corpus's first geostationary thermal-infrared family. The registry's only other GOES item, `noaa_goes16_abi_cloud_mask_netcdf_u8`, was rejected for shipping NetCDF container bytes; it is also a different product, satellite and width.

## Source and rights

- Source: Microsoft Planetary Computer STAC collection `goes-cmi`, asset `C13_2km`.
  - Blobs: `https://goeseuwest.blob.core.windows.net/noaa-goes-cogs/goes-18/ABI-L2-MCMIPF/<yyyy>/<doy>/20/OR_ABI-L2-MCMIPF-M6_G18_s…_CMI_C13.tif`.
  - Each blob is the Cloud-Optimized GeoTIFF export (stactools-goes 0.1.8) of NOAA's `OR_ABI-L2-MCMIPF-M6_G18_…nc`. The source NetCDF name is pinned and checked against `NC_GLOBAL#dataset_name`.
- Access: anonymous short-lived Planetary Computer token, fetched fresh each run from `https://planetarycomputer.microsoft.com/api/sas/v1/token/goeseuwest/noaa-goes-cogs`. No account or key is needed.
- Download: 12 files, 431,073,260 bytes. Each has a pinned exact Content-Length and Azure Content-MD5.
- License: NOAA Open Data Dissemination (NODD); U.S. Government work.
  - https://registry.opendata.aws/noaa-goes/: "NOAA data disseminated through NODD are open to the public and can be used as desired". It requests attribution, forbids implying endorsement, and forbids presenting modified data as unaltered. The page covers GOES-18 as operational GOES-West.
  - NODD FAQ: "free for all users to access with no use restrictions and do not require any registration". It names Microsoft Azure as one of the three NODD cloud partners.
  - Caveat: the GOES-R NetCDF boilerplate `license='Unclassified data. Access is restricted to approved users only.'` is copied into the COG metadata. It is a legacy ground-segment attribute contradicted by NOAA's public NODD distribution of these products, and it is disclosed in the manifest and README.

## Shape and conversion

- Natural record: one complete ABI Mode-6 full-disk scan (about 10 min), 5424 × 5424 on the GOES-R fixed grid (2 km at nadir, projection longitude 137° W).
- Scope: the 20:00 UTC scan on the 15th of each month, October 2025 to September 2026.
  - The card proposed calendar 2025. The builder narrowed the window because the January–March 2025 COGs use a different encoding (SampleFormat 2 int16, nodata −1) and 2025-04-15 has no 20:00 scan.
- Decode, pure standard-library Python:
  - classic little-endian TIFF primary IFD: 5424², 16-bit, SampleFormat 1, Deflate, Predictor 1, 512² tiles (121), GDAL_NODATA 65535;
  - zlib-inflate each tile, requiring exactly 524,288 bytes;
  - crop the 304-pixel right and bottom edge tiles;
  - write row-major little-endian uint16 unchanged.
- Not used: overview IFDs, the DQF layer, other bands.
- Packing is recorded per sample in the index and not applied: BT_K = 89.620003 + 0.06145332·code, valid range 0..4095, fill 65535.
- Missing values: fill is kept in place. The off-disk region is 6,373,440 px (21.66%), the same pixel set in every scan. There is one on-disk fill pixel in total, in 2026-07.

## Accepted output

- Primary samples: 12
- Primary values: 353,037,312
- Primary bytes: 706,074,624
- Per-sample size: 29,419,776 values / 58,839,552 bytes; median 29,419,776 values
- Valid codes overall: 1513..3955 (182.6–332.7 K); 1,744–2,057 distinct codes per scan
- Median on-disk BT per scan: 283.3–287.2 K
- Aggregate SHA-256 of the samples in scan order: `37007cf2f0cd991673ba0a187823f6f82260dd4b84c219e7ba24b202b05bcd1e`

| month | code min..max | distinct | BT min/max/median K |
|---|---|---|---|
| 2025-10 | 1615..3679 | 1781 | 188.9 / 315.7 / 285.4 |
| 2025-11 | 1600..3662 | 1778 | 187.9 / 314.7 / 284.1 |
| 2025-12 | 1552..3653 | 1744 | 185.0 / 314.1 / 283.7 |
| 2026-01 | 1513..3631 | 1775 | 182.6 / 312.8 / 285.7 |
| 2026-02 | 1586..3726 | 1828 | 187.1 / 318.6 / 286.6 |
| 2026-03 | 1583..3844 | 1963 | 186.9 / 325.8 / 287.2 |
| 2026-04 | 1592..3888 | 1956 | 187.5 / 328.6 / 284.6 |
| 2026-05 | 1580..3891 | 2001 | 186.7 / 328.7 / 285.0 |
| 2026-06 | 1543..3955 | 2057 | 184.4 / 332.7 / 285.4 |
| 2026-07 | 1571..3860 | 1967 | 186.2 / 326.8 / 284.9 |
| 2026-08 | 1586..3780 | 1900 | 187.1 / 321.9 / 283.3 |
| 2026-09 | 1606..3821 | 1910 | 188.3 / 324.4 / 284.5 |

Known weakness: about 21.7% of each sample is the identical constant off-disk fill region. It comes from the source and is kept in place, not stripped.

## Judge checks

- **Gate:** `python3 tools/autocollect/gate.py staging/mpc_goes18_abi_cmi_c13_fulldisk_u16` passed with no warnings.
- **verify.sh:** I ran it (25 s). All 12 samples re-derive byte-identically with the independent seek-based decoder; sha256s are unique; index fields and manifest totals match.
- **build.sh:** reads only local files (no curl or HTTP).
- **Download log:** 12 files validated against size and MD5. The access token never appears in the logs.
- **Byte inspection** (`/tmp/autocollect/goes18/`, standard-library `array`):
  - Seams: neighbour differences across tile seams equal within-tile differences, so assembly is correct.
  - Geometry: the disk touches the left and right edges with a 9-pixel polar margin, consistent with the ABI fixed grid and Earth's oblateness.
  - Fill: the mask is identical across scans except one pixel in 2026-07.
  - Values: BT percentiles are physically plausible. The yearly maximum peaks in June over hot land; cold cloud tops reach about 183–189 K.
  - No widening: the low 2 bits are uniform and every code is ≤4095 or 65535.
  - Independence: consecutive months share about 0.5% identical pixels.
  - Regime: clear-sky warm-flat-region noise (P(|dx|=0) 0.24–0.31) is stable across all months and across production sites (WCDAS/RBU/GCCS). A May–September drop in central-block smoothness is seasonal convection, not a processing change.
- **Metadata:** diffing all 84 GDAL metadata keys, only production_site, production_cluster and overview resampling vary. Scale, offset, valid_range, projection, Mode 6 and Full Disk are identical in all 12 files.
- **Rights:** I opened the NODD GOES registry page and the NODD FAQ; both quotes are verbatim and cover GOES-18 ABI, with Azure named as a NODD partner.
- **Novelty:** `novelty.py` with the blob host and path, the STAC collection and noaa-goes18, plus GOES, CMI and brightness-temperature terms, found no URL, registry or downstream matches beyond this candidate itself. A grep of accepted manifests found no Earth thermal-IR or geostationary family; the only thermal-IR family is `nasa_pds_themis_ir_mosaic_u8`, a Mars 8-bit mosaic.
- **Volume:** 706 MB is comparable to accepted EO rasters (Sentinel-1 GRD 732 MB, Sentinel-2 L2A 616 MB, MOLA 531 MB). The download is 431 MB, so it is not a thin aggregate.
