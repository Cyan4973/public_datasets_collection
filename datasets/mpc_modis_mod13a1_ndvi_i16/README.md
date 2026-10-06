# Terra MODIS MOD13A1 v061 16-day 500 m NDVI (i16)

Draft recipe that collects complete, source-native `int16` NDVI grids from the
Terra MODIS MOD13A1 Collection 6.1 vegetation-index product (layer
`500m_16_days_NDVI`) via the Microsoft Planetary Computer COG mirror.

- **Natural record:** one complete 2400 × 2400 MODIS sinusoidal tile for one
  16-day composite period (463.3 m cells), stored as NDVI × 10000.
- **Scope:** 24 land-dominant tiles on six continents × two opposite-season
  2024 composite periods (DOY 017 = 2024-01-17..02-01, DOY 193 =
  2024-07-11..07-26) = 48 samples, 5,760,000 values each, 552,960,000 bytes in
  total.
- **Homogeneity:** one product (MOD13A1), one sensor (Terra), one collection
  (6.1), one layer (NDVI), one scale (0.0001), one grid, one fill (-3000). EVI,
  Aqua MYD13A1, 250 m MOD13Q1, VI quality, and reflectance layers are excluded.
  Each of those would be a separate family.

| continent | tiles (area) |
|---|---|
| north_america | h09v05 (US southwest plateaus), h10v05 (US south-central), h10v04 (northern Great Plains), h11v04 (Upper Midwest), h11v03 (Canadian boreal/prairie) |
| south_america | h11v09 (western Amazon), h12v10 (Bolivia/Mato Grosso), h13v10 (Cerrado), h12v11 (Gran Chaco) |
| europe | h19v04 (Pannonian basin/Balkans), h20v03 (European Russia) |
| africa | h18v07 (Sahel, Niger), h19v08 (Cameroon/CAR), h20v09 (Congo basin), h21v08 (East African highlands), h20v11 (Kalahari/southern Africa) |
| asia | h21v05 (Mesopotamia/Levant), h23v05 (Afghanistan/Pakistan), h25v05 (Tibet/Himalaya), h25v06 (Indo-Gangetic plain), h27v06 (south China/Indochina), h25v04 (Mongolia) |
| oceania | h29v11 (western-central Australia), h30v11 (eastern interior Australia) |

## Values and missing data

Valid NDVI is `-2000..10000` (that is, -0.2..1.0). `-3000` is the product
`_FillValue`. In this product it marks water, ocean, and pixels with no
retrieval. Over land, the composite mostly interpolates cloud gaps (header
QA shows `QAPERCENTNOTPRODUCEDCLOUD` 0 on probed tiles), so fill is mostly
the land/water mask. The probed fill fractions barely change between the two
periods. Fill is kept in place
because it is source-native. Tiles were picked before download from 53
probed candidates so that the overview-estimated fill is at most 10%. Build
and verify reject any sample with more than 15% fill and any value outside
the valid range or the fill value.

Realized output (build of 2026-10-05):

- Fill per sample is 0.00–12.7%, and 44 of 48 samples are under 5%. The
  maximum is h19v04, whose Adriatic coast makes it 12.5–12.7%; the overview
  had estimated 10%.
- Valid values span -2000..9996. Pixels at exactly -2000 are at most 0.02%
  of any sample.
- Distinct values per sample range from 5,605 (the h29v11 desert) to 11,972.
- Shannon entropy is 10.5–13.0 bits/value, median 12.2.
- zlib-6 compresses spot-checked samples only to 72–82% of their raw size.
- Between a tile's two periods, 87.5–100% of pixels change.

## License

The STAC collection's license link
(`https://lpdaac.usgs.gov/data/data-citation-and-policies/`) redirects to NASA
Earthdata *Data Use Guidance*: "Unless the content is marked with a use
restriction or license, data provided from a NASA-led mission are licensed as
Creative Commons Zero (CC0). While there are no restrictions on the use of
these data, data users are very strongly urged to cite the data used in their
work products." The STAC `license` field says `proprietary`, but it only
points to that link. NASA LP DAAC is listed as producer and licensor, and
MOD13A1 carries no product-specific restriction. The accepted
`modis_active_fire_mask_u8` relies on the same evidence chain.

Cite: Didan, K. (2021). MODIS/Terra Vegetation Indices 16-Day L3 Global 500m
SIN Grid V061. NASA EOSDIS LP DAAC. https://doi.org/10.5067/MODIS/MOD13A1.061

## Run

From the repository root:

```bash
bash staging/mpc_modis_mod13a1_ndvi_i16/download.sh   # ~575.5 MB, 48 COGs
bash staging/mpc_modis_mod13a1_ndvi_i16/build.sh
bash staging/mpc_modis_mod13a1_ndvi_i16/verify.sh
```

- `download.sh` fetches only the 48 URLs pinned in `sources.tsv`. The
  container needs the anonymous, read-only, roughly 45-minute SAS signature
  that Planetary Computer issues to anyone at
  `/api/sas/v1/token/modiseuwest/modis-061-cogs`. The signature is cached
  under a mode-700 directory, refreshed every 20 minutes, and never printed.
  Transfers are resumable (`curl -C -`, with stall detection). Each file must
  match its pinned byte size and Azure `x-ms-blob-content-md5`. After that,
  every header is checked for structure and embedded HDF-EOS metadata
  (SHORTNAME `MOD13A1`, VERSIONID `61`, platform `Terra`, granule ID, tile
  numbers, range start date, `_FillValue`, `valid_range`, scale). Finally,
  SHA-256 receipts are written.
- `build.sh` (`scripts/build_samples.py` + `scripts/mod13a1_cog.py`) decodes
  IFD0 only, ignoring the 1200/600/300 overviews. It inflates the 25 Deflate
  tiles with exact-length checks, crops the edge padding (2400 = 4 × 512 +
  352), and writes the unchanged int16 grid row-major as little-endian. It
  also writes `index/<id>/samples.jsonl`, with min, max, and sums computed
  from the stored int16 values, plus `filtered/<id>/ingest_stats.json`.
- `verify.sh` (`scripts/verify_samples.py`) recomputes all statistics from
  the sample bytes and applies the same missing-value policy. It then
  re-decodes every source COG with a separately written TIFF reader and
  requires byte-identical grids. It also checks the realized scope (24 tiles
  × 2 periods, continent counts, manifest totals), that no two grids are
  duplicates, and that at least 5% of pixels change between a tile's two
  periods.

## Discovery

`scripts/probe.py` documents how the plan was resolved. It runs STAC
`/search` on `modis-13A1-061` with `modis:horizontal-tile`,
`modis:vertical-tile`, and the composite start date, keeping only IDs that
start with `MOD13A1.` (the platform property is empty, and Aqua `MYD13A1`
items match the same query). It then range-reads only each COG header and
its single-tile 300 × 300 overview (about 150 KB) to record the size, MD5,
structure, and an estimated fill fraction. Overview values come from a
resampling that overshoots, so they are used only for the fill estimate. The
probe output for all 53 candidates is
`scripts/probe_candidates_20261005.tsv`. Item IDs include the production
timestamp. If LP DAAC reprocesses a granule, the pinned URL or MD5 stops
matching and `download.sh` fails instead of silently substituting a
different file.

Decoders were self-tested on a synthetic 2400² COG with the same layout:
512² tiles, random edge padding, GDAL ghost leaders/trailers, three
overviews, and GDAL metadata. Both decoders were byte-exact. The tests also
confirmed that wrong item/tile metadata, truncation, a corrupt Deflate tile,
and out-of-range values are rejected.
