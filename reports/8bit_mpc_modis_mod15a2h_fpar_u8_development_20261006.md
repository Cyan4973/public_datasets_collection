# MODIS MOD15A2H 8-day FPAR uint8 development

## Outcome

Accepted `mpc_modis_mod15a2h_fpar_u8`. It holds complete Terra MODIS
MOD15A2H Collection 6.1 `Fpar_500m` grids from the Microsoft Planetary
Computer COG mirror, emitted as source-native uint8.

This is the corpus's first vegetation biophysical-variable family (FPAR or
LAI) at any width. The nearest families are:
- the accepted `mpc_modis_mod13a1_ndvi_i16`: a different product and file,
  a 10^4-scaled band-ratio index, holding DOY 017/193;
- `modis_active_fire_mask_u8`: MOD14A2 fire classes.

All three share only the Planetary Computer `modis-061-cogs` container.
FPAR is spatially correlated with NDVI: the MOD15 back-up algorithm is an
NDVI relation, and 16 of the 24 tiles overlap with the NDVI recipe. As
stored material, though, it is a saturating 0..100 fraction lattice from a
radiative-transfer LUT inversion, with a land-cover reserved-code block. The
composite dates (DOY 049/137/225/313) avoid the NDVI periods.

Breadth note: 8-bit Earth-observation rasters are already well populated.
Examples are S1 coherence, the sea-ice CDR, JRC water occurrence,
WorldCover, S2 SCL, MODIS fire and IMS snow. This family is accepted as a
new quantity that is materially denser (median ~5.8 bits/value) than the
near-binary percent rasters already held.

## Source and rights

- Source: STAC collection `modis-15A2H-061` on Planetary Computer; container
  `modiseuwest/modis-061-cogs/MOD15A2H/`
- Pinned objects: 96 exact item IDs, including production timestamps.
  `sources.tsv` pins each one's byte size and Azure `x-ms-blob-content-md5`,
  and SHA-256 receipts are written at download time.
- Download bytes: 410,569,555
- Access: Planetary Computer's anonymous read-only SAS signature (no
  account or key). It is cached in a mode-700 directory and never logged.
- License: CC0 1.0. The STAC `rel=license` link
  (`https://lpdaac.usgs.gov/data/data-citation-and-policies/`) returns 301
  to NASA Earthdata Data Use Guidance: "Unless the content is marked with a
  use restriction or license, data provided from a NASA-led mission are
  licensed as Creative Commons Zero (CC0)." NASA LP DAAC is listed as
  producer and licensor, and MOD15A2H carries no product restriction. This
  is the same chain as `mpc_modis_mod13a1_ndvi_i16` and
  `modis_active_fire_mask_u8`.
- Citation: Myneni, Knyazikhin, Park (2021), doi:10.5067/MODIS/MOD15A2H.061

## Shape and conversion

Each natural record is one complete 2400 × 2400 MODIS sinusoidal tile
(463.3 m cells) for one 8-day composite.

Stored values:
- 0..100 = FPAR × 100 (scale 0.01).
- 249..255 are the product's embedded fill and land-cover legend. Here only
  250 urban, 253 barren, 254 water and 255 fill occur.
- 248 is tolerated but absent.

The decoder reads only IFD0: uint8, SampleFormat 1, Deflate, predictor 1,
25 tiles of 512². It inflates each tile with exact-length checks, crops the
edge padding (2400 = 4 × 512 + 352), and writes row-major (y, x) uint8. It
does no rescaling, remapping, resampling or concatenation, and ignores the
1200/600/300 overviews.

Build and verify both treat the following as fatal:
- any value in 101..247
- valid fraction below 0.70
- fewer than 50 distinct valid values
- duplicate grids
- size or MD5 mismatches
- unexpected TIFF structure or HDF-EOS metadata (SHORTNAME, VERSIONID,
  Terra, granule ID, tile, dates, DOI, Fpar long_name, units, fill, valid
  range, scale, offset; NDAYS_COMPOSITED must be within 1..8)
- corrupt Deflate streams

Verify additionally requires at least 5% pixel change between consecutive
composites.

Scope: 24 tiles × 2024 DOY 049, 137, 225 and 313 (one per season).

| Continent | Tiles |
|---|---|
| North America | 5 (h09v05 h10v04 h10v05 h11v03 h11v04) |
| South America | 4 (h12v09 h13v10 h12v11 h12v12) |
| Europe | 3 (h19v03 h19v04 h20v03) |
| Africa | 5 (h19v08 h20v09 h21v08 h20v10 h20v11) |
| Asia | 5 (h22v03 h23v04 h25v06 h26v04 h27v06) |
| Oceania | 2 (h29v11 h30v11) |

Tiles were selected before download. 93 candidates were screened via their
300 × 300 overviews at DOY 193; 38 had an overview valid fraction of at
least 0.80, and 24 were named for biome spread.

## Accepted output

| Metric | Value |
|---|---|
| Primary samples | 96 (24 tiles × 4 composites) |
| Values per sample | 5,760,000 (2400 × 2400) |
| Primary values | 552,960,000 |
| Primary bytes | 552,960,000 |
| Valid value span | 0..100 |
| Valid fraction per sample | 0.833–0.995 (minimum h12v12, Pacific coast) |
| Reserved codes (all samples) | 250: 2,928,932; 253: 6,678,392; 254: 19,383,012; 255: 298,052; 248/249/251/252: 0 |
| Distinct valid values per sample | 72–101 |
| Mean valid FPAR DN per sample | 2.9 (h23v04 DOY 049) – 84.1 (h12v09 DOY 225) |
| Pixels changing between consecutive composites | 70.1%–98.7% |
| Shannon entropy | 2.7–6.5 bits/value (median 5.8) |
| zlib-6 ratio | 0.15–0.74 (median 0.57) |
| NDAYS_COMPOSITED | 8 for 91 samples; 7 (h12v09, h13v10 DOY 049), 6 (h10v05, h11v04 DOY 313), 5 (h09v05 DOY 313) |
| QAPERCENTMAINMETHOD | 0–100 (winter and cloudy composites rely on the back-up algorithm) |

- Each tile's reserved-code mask is identical across its four composites,
  so it is a static land-cover/water map. All temporal variation is in
  0..100.
- Aggregate decoded SHA-256 (samples concatenated in index order):
  `c7fd60d5c4555b1050a9ed5c287f381c978a607b850317a1433ef3c299905c1b`

## Judge checks

- **Gate:** `gate.py staging/mpc_modis_mod15a2h_fpar_u8` passes with no
  warnings (96 samples, median 5,760,000 values, width 8).
- **Verify:** I ran `verify.sh` myself (exit 0, about 61 s). It re-decoded
  all 96 COGs with its separate TIFF reader and got byte-identical grids.
  Statistics, scope (continent counts 5/4/3/5/5/2) and totals also matched.
- **Build is local-only:** `build.sh` reads only `sources.tsv`, the receipts
  and the local rasters.
- **Download provenance:** the first run (00:34) fetched all files but
  failed the then-strict `NDAYS_COMPOSITED == 8` check. That check lives in
  `scripts/mod15a2h_cog.py` and was relaxed to 1..8 at 00:36. The current
  run (00:40) re-validated all 96 cached files by size and MD5 and passed
  96 header checks. No script changed after it.
- **Bytes:** I inspected six samples (Amazon, European Russia in winter,
  Kazakh winter, Midwest in summer, Indo-Gangetic, arid Australia) with
  standard-library Python.
  - Distributions match each biome. The Amazon saturates at 89–91; winter
    tiles are near 0; arid Australia is 9–29.
  - Codes above 100 are only 250/253/254/255.
  - Against the COG's own GDAL 300 × 300 overview, block means agree to a
    mean absolute difference of 1.1–4.2 DN, versus 7.6–26 DN when
    transposed. So the orientation is right.
  - Neighbour differences across the 512-pixel tile seams equal those of
    interior control lines.
  - The last row and column hold real data (54–94 distinct values), so the
    padding crop is right.
  - Consecutive composites differ by a mean of 3.7–53 DN, so samples are
    not near-duplicates.
- **Selection:** I reproduced the screen claim from
  `scripts/probe_screen_doy193_20261006.tsv` (93 screened, 38 passing, all
  24 chosen tiles among them). All 96 pins match `sources.tsv`.
- **License:** I fetched the STAC collection and followed the LP DAAC 301
  to the Earthdata CC0 statement myself.
- **Novelty:** `novelty.py` found no FPAR, LAI or MOD15 family locally, in
  the registry, in the ledger or downstream. The only matches were the same
  host, for different products.
- **Secrets:** no SAS signature, key or token appears in any recipe file,
  TSV or log. `staging/*` (including `__pycache__`) is gitignored.
