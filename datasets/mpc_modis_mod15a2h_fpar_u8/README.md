# Terra MODIS MOD15A2H v061 8-day 500 m FPAR (u8)

This recipe collects complete, source-native `uint8` FPAR grids from the
Terra MODIS MOD15A2H Collection 6.1 LAI/FPAR product (layer `Fpar_500m`) via
the Microsoft Planetary Computer COG mirror.

- **Quantity:** fraction of incident photosynthetically active radiation
  (400-700 nm) absorbed by the green canopy. It is retrieved per cell by
  inverting a 3-D radiative-transfer look-up table against Terra MODIS
  surface reflectance; an empirical NDVI relation is the back-up algorithm.
  It is then composited over 8 days. LP DAAC describes this as choosing
  "the best pixel available" in the period; per the product user guide,
  that is the maximum-FPAR daily retrieval. Stored value = FPAR × 100 on the
  integer lattice 0..100. Non-vegetated cells carry the product's land-cover
  fill classes 249..255 in the same byte.
- **Natural record:** one complete 2400 × 2400 MODIS sinusoidal tile
  (463.3 m cells) for one 8-day composite.
- **Scope:** 24 land-dominant tiles on six continents × four 2024 composites
  (DOY 049 = Feb 18-25, 137 = May 16-23, 225 = Aug 12-19, 313 = Nov 8-15)
  = 96 samples, 5,760,000 values each, 552,960,000 bytes in total. The
  download is 96 COGs, 410,569,555 bytes.
- **Homogeneity:** one product (MOD15A2H), one sensor (Terra), one collection
  (6.1), one layer (Fpar_500m), one scale (0.01), one grid, one fill legend.
  Excluded: `Lai_500m` (a different quantity, scale 0.1), the QC bit-field
  layers, the StdDev layers, Aqua `MYD15A2H`, and combined `MCD15A2H`. Each
  of those would be a separate family.

| continent | tiles (area) |
|---|---|
| north_america | h09v05 (US southern Rockies/southern Plains), h10v04 (northern Great Plains), h10v05 (US south-central), h11v03 (Canadian prairie/boreal), h11v04 (Upper Midwest) |
| south_america | h12v09 (eastern Amazon), h13v10 (Brazilian Cerrado), h12v11 (Gran Chaco/Paraná), h12v12 (central Argentina/central Chile) |
| europe | h19v03 (Poland/Belarus/Baltics), h19v04 (Pannonian basin/Balkans), h20v03 (European Russia) |
| africa | h19v08 (Cameroon/CAR), h20v09 (Congo basin), h21v08 (East African highlands), h20v10 (Angola/Zambia miombo), h20v11 (Kalahari/southern Africa) |
| asia | h22v03 (West Siberian plain/northern Kazakhstan), h23v04 (eastern Kazakhstan/Tian Shan), h25v06 (Indo-Gangetic plain), h26v04 (northeast China), h27v06 (south China/Indochina) |
| oceania | h29v11 (western-central Australia), h30v11 (eastern interior Australia) |

### Why these tiles and dates

`scripts/probe.py` screened 93 land candidate tiles at DOY 193
(`scripts/probe_screen_doy193_20261006.tsv`). Only tiles whose 300 × 300
overview had at least 80% of pixels in 0..100 were eligible, and 38 passed.
Of those, 24 were named for continental and biome spread before any
download: boreal, steppe, cropland, tropical forest, savanna, miombo,
semi-arid, monsoon Asia, and Australian interior. This mirrors how the
accepted `mpc_modis_mod13a1_ndvi_i16` chose its tiles. Oceania has only two
tiles because none of the other ten screened Australian, New Guinea or
Borneo tiles clears the threshold (coastal tiles are mostly ocean, coded
254).

The four composites are 88 days apart, one per season. They deliberately
avoid DOY 017 and 193, the two 16-day periods the accepted MOD13A1 NDVI
recipe already holds.

## Values and missing data

Valid FPAR is `0..100` (that is, 0.00-1.00). Every file embeds the source
legend for the reserved codes:

| code | meaning (embedded `MOD15A2_FILLVALUE_DOC`) |
|---|---|
| 255 | `_FillValue`: surface reflectance was fill, or land cover was fill |
| 254 | land cover is perennial salt or inland fresh water (ocean pixels appear here too) |
| 253 | barren, sparse vegetation (rock, tundra, desert) |
| 252 | perennial snow, ice |
| 251 | "permanent" wetlands/inundated marshlands |
| 250 | urban/built-up |
| 249 | "unclassified" or not able to determine |

Code 248 is not in the embedded legend. It is accepted only as the
remaining code of the reserved block and is counted separately; it is not
expected to occur. All reserved codes are kept in place as stored. They are
mostly static (the land-cover map), not cloud gaps: cloudy days fall back to
the back-up algorithm, which still writes a value, and the 8-day
compositing fills the rest.

Build and verify reject any value in `101..247`, any sample whose valid
fraction is below 0.70, and any sample with fewer than 50 distinct valid
values. Verify also rejects duplicate grids, and any tile where fewer than
5% of pixels change between consecutive composites. Per-sample counts for
each reserved code are written to the index and to
`filtered/<id>/ingest_stats.json`.

Probe evidence before download:

- The overview-estimated valid fraction for the 96 pinned items is
  0.82–0.996.
- It barely moves between seasons for a given tile (for example h11v03 is
  0.92–0.95 and h20v03 is 0.97–0.98), as expected for a land-cover-driven
  mask.
- Overview values in 101..247 are resampling artifacts at class boundaries.
  Two range-read full-resolution primary tiles had none: h18v04 DOY 193
  (84.5% valid, codes 250/253/254/255 present) and h12v12 DOY 225 (99.0%
  valid).

Realized output (build of 2026-10-06; 96 samples, 552,960,000 bytes):

- The valid fraction per sample is 0.833–0.995. The minimum is h12v12,
  whose Pacific coast is coded 254, and 80 of 96 samples are above 0.90.
- Reserved codes summed over all samples:

  | code | pixels |
  |---|---|
  | 250 urban | 2,928,932 |
  | 253 barren | 6,678,392 |
  | 254 water | 19,383,012 |
  | 255 fill | 298,052 |

  Codes 248, 249, 251 and 252 never occur.
- Each tile's reserved-code mask (every code count) is identical in all
  four composites. So the mask is the static land-cover/water map, and all
  temporal variation lives in the 0..100 values.
- Valid values span 0..100. Distinct valid values per sample range from 72
  (h29v11, arid western Australia, where FPAR rarely exceeds about 0.9) to
  101.
- Mean valid FPAR per sample ranges from 2.9 (h23v04, snowy February) to
  84.1 (tropical forest).
- Between consecutive composites of a tile, 70–99% of pixels change.
- Shannon entropy is 2.7–6.5 bits/value, median 5.8.
- zlib-6 compresses samples to 15–74% of raw, median 57%. The two most
  compressible samples are h23v04 at DOY 049 (15%) and DOY 313 (28%), both
  winter composites of the Kazakh steppe/Tian Shan with near-zero FPAR.
- `NDAYS_COMPOSITED` (daily inputs per composite) is 8 for 91 samples, and
  5–7 for five autumn and winter composites.
- `QAPERCENTMAINMETHOD` ranges from 0 to 100.

Caveat for the judge: the per-file `QAPERCENTMAINMETHOD` and
`QAPERCENTGOODFPAR` vary widely. Some winter or cloudy composites drop
close to zero (h19v03 and h20v03 at DOY 313, h20v03 and h22v03 at DOY 049),
meaning most pixels there come from the back-up empirical algorithm. Those
pixels are still the product's published FPAR values, on the same lattice
and scale, and they are kept without QC filtering. Winter composites are also
more compressible: the smallest COG is h23v04 DOY 049 at 1.4 MB, against a
typical 4-5 MB.

## License

The STAC collection's license link
(`https://lpdaac.usgs.gov/data/data-citation-and-policies/`) redirects to NASA
Earthdata *Data Use Guidance*: "Unless the content is marked with a use
restriction or license, data provided from a NASA-led mission are licensed as
Creative Commons Zero (CC0). While there are no restrictions on the use of
these data, data users are very strongly urged to cite the data used in their
work products." The STAC `license` field says `proprietary`, but it only
points to that link. NASA LP DAAC is listed as producer and licensor, and
MOD15A2H carries no product-specific restriction. The accepted
`modis_active_fire_mask_u8` and `mpc_modis_mod13a1_ndvi_i16` rely on the same
evidence chain.

Cite: Myneni, R., Knyazikhin, Y., Park, T. (2021). MODIS/Terra Leaf Area
Index/FPAR 8-Day L4 Global 500m SIN Grid V061. NASA EOSDIS LP DAAC.
https://doi.org/10.5067/MODIS/MOD15A2H.061

## Novelty and nearest families

`tools/autocollect/novelty.py` found the same host only: the
`modis-061-cogs` container also serves the accepted MOD14A2 fire mask (u8)
and MOD13A1 NDVI (i16) recipes. Those are different products in different
files, and no FPAR or LAI raster exists locally or downstream at any width.

FPAR is spatially correlated with NDVI, because the back-up algorithm is an
NDVI relation and both respond to green canopy. As stored material it
differs in several ways:

- it is a saturating 0..100 fraction on a 101-level lattice, not a 10^4-scaled
  index;
- its reserved-code block encodes land cover rather than a single fill;
- it is an 8-day best-retrieval composite of an RT-model inversion.

This is a third MODIS product from the same mirror. That is a breadth
consideration for the judge, not a homogeneity problem.

## Run

From the repository root:

```bash
bash staging/mpc_modis_mod15a2h_fpar_u8/download.sh   # ~410.6 MB, 96 COGs
bash staging/mpc_modis_mod15a2h_fpar_u8/build.sh
bash staging/mpc_modis_mod15a2h_fpar_u8/verify.sh
```

`DATA_DIR` may be relative to the repository root (default `.data`) or
absolute.

- `download.sh` fetches only the 96 URLs pinned in `sources.tsv`.
  - The container needs the anonymous, read-only, roughly 45-minute SAS
    signature that Planetary Computer issues to anyone at
    `/api/sas/v1/token/modiseuwest/modis-061-cogs`. The signature is cached
    under a mode-700 directory and never printed. It is refreshed every 20
    minutes and after any failed transfer; failed transfers also back off
    before retrying.
  - Transfers are resumable (`curl -C -`, with stall detection rather than a
    hard timeout).
  - Each file must match its pinned byte size and Azure
    `x-ms-blob-content-md5`.
  - Every header is then checked for structure and embedded HDF-EOS
    metadata: SHORTNAME `MOD15A2H`, VERSIONID `61`, platform `Terra`, granule
    ID, tile numbers, range start and end dates, `NDAYS_COMPOSITED` within
    1..8 (the number of daily MOD15A1H inputs that entered the composite: 8
    for 91 files, 7 for h12v09 and h13v10 at DOY 049, 6 for h10v05 and
    h11v04 at DOY 313, 5 for h09v05 at DOY 313; recorded per sample), the
    DOI, the Fpar `long_name`, `units`, `_FillValue` 255, `valid_range`
    0..100, `scale_factor` 0.01, and `add_offset` 0.
  - Finally, SHA-256 receipts are written.
- `build.sh` (`scripts/build_samples.py` + `scripts/mod15a2h_cog.py`):
  - decodes IFD0 only, ignoring the 1200/600/300 overviews;
  - inflates the 25 Deflate tiles with exact-length checks and crops the
    edge padding (2400 = 4 × 512 + 352);
  - writes the unchanged uint8 grid row-major;
  - also writes `index/<id>/samples.jsonl`, with min, max, sums and
    per-code counts computed from the stored bytes, plus
    `filtered/<id>/ingest_stats.json`.
- `verify.sh` (`scripts/verify_samples.py`):
  - recomputes all statistics from the sample bytes with a different
    histogram method, and applies the same missing-value policy;
  - re-decodes every source COG with a separately written TIFF reader and
    requires byte-identical grids;
  - checks the realized scope (24 tiles × 4 composites, continent counts,
    manifest totals), that no two grids are duplicates, and that
    consecutive composites of each tile change.

## Discovery and self-test

`scripts/probe.py` documents how the plan was resolved:

- It runs STAC `/search` on `modis-15A2H-061` with `modis:horizontal-tile`,
  `modis:vertical-tile`, and the composite start date, keeping only IDs
  that start with `MOD15A2H.`. The platform property is empty, and
  `MYD15A2H` and `MCD15A2H` items match the same query.
- It then range-reads only each `Fpar_500m` COG header and its single-tile
  300 × 300 overview (about 90 KB per item) to record size, MD5, structure,
  QA percentages, and overview class fractions.
- Item IDs include the production timestamp. If LP DAAC reprocesses a
  granule (the files say "further update is anticipated"), the pinned URL
  or MD5 stops matching, and `download.sh` fails instead of silently
  substituting a different file.

Both decoders, the header checker, `build.sh`, and `verify.sh` were run end
to end on 96 synthetic 2400² uint8 COGs with the same layout: 512² Deflate
tiles with random edge-padding garbage, three overviews, GDAL metadata with
duplicate and band-role items, and nodata 255. Build output was byte-exact
against the synthetic truth, and verify passed. The tests also confirmed
that each of these is rejected:

- wrong item ID, tile or end date;
- an Aqua `SHORTNAME`;
- an LAI `long_name`;
- predictor 2;
- truncation;
- a corrupt Deflate tile;
- an out-of-domain value (150);
- a low valid fraction;
- a tampered sample.
