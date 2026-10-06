# MODIS MOD13A1 16-day NDVI int16 development

## Outcome

Accepted `mpc_modis_mod13a1_ndvi_i16`: complete Terra MODIS MOD13A1
Collection 6.1 `500m_16_days_NDVI` grids, taken from the Microsoft Planetary
Computer COG mirror and emitted as source-native int16.

This is the corpus's first vegetation-index family. The accepted
`modis_active_fire_mask_u8` shares only the Planetary Computer host. It is a
different product and file (MOD14A2 8-bit fire classes). The nearest 16-bit
raster family, `sentinel2_l2a_reflectance_cogs_u16`, holds unsigned surface
reflectance from a different sensor. Here the NDVI is the official product
layer, not a local derivation from reflectance.

## Source and rights

- Source: STAC collection `modis-13A1-061` on Planetary Computer; container
  `modiseuwest/modis-061-cogs/MOD13A1/`
- Pinned objects: 48 exact item IDs, including their production timestamps.
  Each has its byte size and Azure `x-ms-blob-content-md5` pinned in
  `sources.tsv`, and a SHA-256 receipt is written at download time.
- Download bytes: 575,539,183
- Access: Planetary Computer's anonymous read-only SAS signature (no account
  or key). It is cached in a mode-700 directory and never logged.
- License: CC0 1.0. The STAC `rel=license` link
  (`https://lpdaac.usgs.gov/data/data-citation-and-policies/`) returns 301 to
  the NASA Earthdata Data Use Guidance: "Unless the content is marked with a
  use restriction or license, data provided from a NASA-led mission are
  licensed as Creative Commons Zero (CC0)." NASA LP DAAC is listed as
  producer and licensor, and MOD13A1 carries no product restriction. The
  STAC `license: proprietary` field only points to that link. This is the
  same evidence chain as the accepted `modis_active_fire_mask_u8`.
- Citation: Didan, K. (2021), doi:10.5067/MODIS/MOD13A1.061

## Shape and conversion

Each natural record is one complete 2400 × 2400 MODIS sinusoidal tile
(463.31 m cells) for one 16-day composite period. Stored values are
NDVI × 10000: valid range -2000..10000, fill -3000.

The decoder reads only IFD0, the primary int16 plane:
- SampleFormat 2, Deflate, predictor 1, 25 tiles of 512²
- Embedded HDF-EOS metadata names the source `.hdf` granule, scale 10000,
  valid range and fill.

It inflates each tile with exact-length checks, crops the edge padding
(2400 = 4 × 512 + 352), and writes row-major (y, x) little-endian int16. It
does no rescaling, resampling, remapping or concatenation. The overviews
(1200/600/300) are ignored. They are resampled and overshoot the valid range.

Fill -3000 (mostly water) is kept in place as source-native data. Build and
verify both treat the following as fatal:
- any other value outside [-2000, 10000]
- fill above 15%
- fewer than 1,000 distinct valid values
- duplicate grids
- size or MD5 mismatches
- unexpected TIFF structure or metadata
- corrupt Deflate streams

Scope is 24 land-dominant tiles × 2024 DOY 017 (Jan 17–Feb 1) and DOY 193
(Jul 11–26):

| Continent | Tiles |
|---|---|
| North America | 5 |
| South America | 4 |
| Europe | 2 |
| Africa | 5 |
| Asia | 6 |
| Oceania | 2 |

Tiles were chosen before download from 53 probed candidates by
overview-estimated fill.

## Accepted output

| Metric | Value |
|---|---|
| Primary samples | 48 (24 tiles × 2 periods) |
| Values per sample | 5,760,000 (2400 × 2400) |
| Primary values | 276,480,000 |
| Primary bytes | 552,960,000 |
| Valid value span | -2000..9996 |
| Total fill pixels | 3,903,238 |
| Fill per sample | 0.004%–12.68% (median 0.15%; 44 of 48 under 5%; maximum h19v04, Adriatic coast) |
| Distinct valid values per sample | 5,605–11,972 (median 11,089) |
| Entropy | 10.5–13.0 bits/value |
| Pixels changing between a tile's two periods | 87.5%–100% |

- Aggregate decoded SHA-256 (samples concatenated in index order):
  `78705e5adbf372c2963fdd40c829eb95c06cecbe44958e03d274382a094f9258`

## Judge checks

- **Gate:** `gate.py staging/mpc_modis_mod13a1_ndvi_i16` passes with no
  warnings.
- **Verify:** I ran `verify.sh` myself (exit 0, about 29 s). It re-decoded
  all 48 COGs with an independent TIFF reader and got byte-identical grids.
  Statistics, scope and totals also matched.
- **Build is local-only:** `build.sh` reads only `sources.tsv`, the receipts
  and the local rasters, with no network.
- **Bytes:** I inspected 12 samples across 6 tiles with `array`/`struct`.
  - Little-endian int16 throughout, with value ranges and medians that match
    each biome. January snow tiles in Russia and Canada are 34–39% negative.
  - Neighbour differences across the 512-pixel tile seams match those inside
    tiles, so tiles are placed correctly.
  - The last row and column hold real data, so the padding crop is right.
  - Fill sits where north-up geography predicts: bottom rows of h19v04,
    top rows of h29v11.
- **Georeferencing:** pixel scale is 463.3127 m and tiepoints equal the
  sinusoidal tile corners, so the grid is native and not reprojected.
- **License:** I fetched the STAC collection and followed the LP DAAC link
  to the Earthdata CC0 statement myself.
- **Novelty:** `novelty.py` found no NDVI, MOD13 or vegetation-index family
  locally, in the registry or downstream. The `evi` hits are substring false
  positives.
- **Secrets:** the logs contain no SAS signature, and the recipe contains no
  credentials. `__pycache__` is gitignored.
- **Size:** 553 MB is above the roughly 100 MB "plenty" guideline but well
  under the 1 GB cap. It buys 48 samples across 24 biomes from a source that
  is vast. Download-to-kept ratio is 96%.
