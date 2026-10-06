# MODIS MOD10A1 daily NDSI snow cover uint8 development

## Outcome

Accepted `mpc_modis_mod10a1_ndsi_snow_cover_u8`. It holds complete Terra MODIS MOD10A1 Collection 6.1 `NDSI_Snow_Cover` grids from the Microsoft Planetary Computer COG mirror, emitted as source-native uint8.

This is the corpus's first per-pixel snow-index family at any width. The nearest families are:
- `noaa_ims_snow_ice_cover_u8`: an analyst-blended 4 km snow/ice/land/water category grid, not a retrieval;
- `noaa_cdr_seaice_conc_nh_daily_u8`: passive-microwave sea-ice percent on a 25 km polar grid;
- `mpc_modis_mod15a2h_fpar_u8`: the same container and 2400² sinusoidal grid, but an 8-day vegetation composite.

All the MODIS recipes share only the Planetary Computer `modis-061-cogs` container; each uses a different product and different files.

**Breadth note.** This is the fourth 8-bit "0–100 plus in-band flags" Earth-observation raster accepted in this collection round, after S1 coherence, the sea-ice CDR and FPAR. That lowers its priority. It is accepted because:
- it is a new quantity in the cryosphere;
- its structure is distinct: daily and cloud-limited, with large cloud (250) and snow-free (0) regions next to textured NDSI;
- the C6.1 screen leaves a gap: codes 1..9 never occur;
- its density sits between the near-binary percent rasters and FPAR: median 2.43 bits/value, against the sea-ice CDR's zlib output of about 7–10% of raw and FPAR's ~5.8 bits/value.

## Source and rights

- **Source:** STAC collection `modis-10A1-061` on Planetary Computer; container `modiseuwest/modis-061-cogs/MOD10A1/`. Only Terra items are used (ID prefix `MOD10A1.`, platform `terra`); Aqua MYD10A1 is excluded.
- **Pinned objects:** 70 exact item IDs, including production timestamps. `sources.tsv` pins each one's byte size and Azure `x-ms-blob-content-md5`, and SHA-256 receipts are written at download time.
- **Download:** 70 COGs, 128,814,601 bytes.
- **Access:** Planetary Computer's anonymous read-only SAS signature (no account or key). It is cached in a mode-700 directory and never logged.
- **License:** CC0 1.0.
  - The STAC `rel=license` link is the NSIDC "Use and Copyright" page: "Data hosted by the NSIDC DAAC are openly shared, without restriction, in accordance with NASA's Earth Science program Data and Information Guidance."
  - NASA Earthdata Data Use Guidance: "Unless the content is marked with a use restriction or license, data provided from a NASA-led mission are licensed as Creative Commons Zero (CC0)."
  - MOD10A1 is NASA Terra MODIS data. The NSIDC product page requires citation ("As a condition of using these data, you must cite the use of this data set"), and the manifest keeps it.
- **Citation:** Hall, D. K. and G. A. Riggs (2021), MODIS/Terra Snow Cover Daily L3 Global 500m SIN Grid, Version 61, NSIDC DAAC, doi:10.5067/MODIS/MOD10A1.061 (subset: the 70 tile-days in `sources.tsv`).

## Shape and conversion

Each natural record is one complete 2400 × 2400 MODIS sinusoidal tile (463.3 m cells) for one day.

Stored values:
- 0..100 = NDSI × 100 of the day's best observation. 0 = snow-free land, including detections reversed by the C6.1 screens.
- Flag codes in the same byte: 200 missing, 201 no decision, 211 night, 237 inland water, 239 ocean, 250 cloud, 254 detector saturated, 255 fill.
- These match the user guide's Table 1 and the `Key` attribute embedded in every file, which download.sh checks.

The decoder reads only IFD0: uint8, SampleFormat 1, Deflate, predictor 1, 25 tiles of 512². It inflates each tile with exact-length checks, crops the edge padding (2400 = 4 × 512 + 352), and writes row-major (y, x) uint8. It does no rescaling, remapping or resampling, and ignores the 1200/600/300 overviews.

Build and verify both treat the following as fatal:
- any value outside the code set
- full-grid valid (0..100) fraction below 0.40
- snow (1..100) fraction below 0.02
- fewer than 20 distinct valid values
- duplicate grids
- size or MD5 mismatches
- unexpected TIFF structure or HDF-EOS metadata

Verify additionally requires at least 5% pixel change between consecutive same-tile observations.

**Selection** (`scripts/select_plan.py`, re-derived by verify):
- Pool: all 815 Terra items in rows v02–v05 on the 1st and 15th of each month, 2023-12-01 to 2024-04-15.
- Keep an item when its 300² overview estimates a valid fraction of at least 0.45 and its PGE header `SNOWCOVERPERCENT` is at least 5.
- No item was picked by hand.
- The 0.45 threshold was set after inspecting the probe table (0.50 kept 53 items on 22 tiles and no European tile). The README discloses this.

## Accepted output

| Metric | Value |
|---|---|
| Primary samples | 70 (28 tiles; 10 dates) |
| Values per sample | 5,760,000 (2400 × 2400) |
| Primary values / bytes | 403,200,000 / 403,200,000 |
| Regions | 7 North American tiles (11 samples), 3 European-edge tiles (3), 18 Asian tiles (56) |
| Samples per date | 6, 5, 5, 7, 4, 8, 12, 11, 8, 4 (2023-12-01 … 2024-04-15) |
| Valid (0..100) fraction | 0.470 / 0.589 / 0.917 (min/median/max) |
| Snow (1..100) fraction | 0.049 / 0.163 / 0.728 |
| Cloud (250) fraction | 0.028 / 0.370 / 0.490 |
| Snow value span | 10..86–100 on every sample (1..9 never occur) |
| Distinct valid values per sample | 77–92 |
| Aggregate class counts | valid 250,854,608 (snow 102,936,843); cloud 140,970,490; ocean 4,822,358; inland water 4,036,937; fill 1,740,512; no decision 774,490; missing 351; detector saturated 176; night 78 |
| Shannon entropy | 1.155 / 2.427 / 5.293 bits/value |
| zlib-6 output, % of raw | 5.4% / 15.4% / 44.6% |
| Same-tile pixel change | 34.8%–92.7% (42 pairs) |
| Max abs(measured snow/land − SNOWCOVERPERCENT) | 4.31 points (h21v04 2024-03-01) |

Aggregate decoded SHA-256 (samples concatenated in index order): `f6c8286131f0fc376444563a1f720fa1f9a8e0e2f12b5f35824af1cb74e2bed4`

Notes:
- Fill (255) covers 12–16% of the two h24v02 samples. This is the off-planet region at the sinusoidal edge near 70° N, and it is source-native.
- Ten high-latitude samples have less than 0.1% snow-free land; every valid pixel there is snow.

## Judge checks

- **Gate:** `python3 tools/autocollect/gate.py staging/mpc_modis_mod10a1_ndsi_snow_cover_u8` gave PASS with no warnings.
- **verify.sh**, run by the judge: succeeded in 40.7 s. The independent decoder is byte-identical on all 70 samples, the selection rule re-derives `sources.tsv`, and all 42 same-tile pairs pass the 5% change floor.
- **build.sh:** reads only `.data/downloads`, `sources.tsv` and the receipts. The scripts import only csv, hashlib, json, struct, zlib and re; there is no network access.
- **Value check:** stdlib histograms on 6 samples spread across dates and regions show only {0, 10..100} plus documented flags. NDSI peaks at 50–80, which is physically plausible.
- **Tile assembly:** neighbour equality at the 512-px tile seams (columns and rows 511/1023/1535/2047) matches non-seam lines, so tiles are assembled correctly.
- **Full-set recompute:** entropy, zlib ratio and the aggregate SHA-256 over all 70 samples match the builder exactly.
- **Probe table:** 815 rows, all terra, all struct_ok and meta_ok. Threshold sweep: 0.40→90 items, 0.45→70, 0.50→53.
- **Embedded metadata:** read from the h19v04 2024-02-01 COG: SHORTNAME MOD10A1, platform Terra, PGEVERSION 6.1.2, Key string matching the code table.
- **Rights:** fetched the NSIDC citing page, the NASA Earthdata Data Use Guidance and the MOD10A1 v61 landing page. No SAS signature appears in the recipe, the probe table, or the download, build and verify logs.
- **Novelty:** `novelty.py --url .../modis-061-cogs/MOD10A1/ --terms NDSI MOD10A1 "snow cover" snow_cover MYD10A1 10A1` found only same-host product matches and no downstream hits.
- **Documentation corrections** (data unaffected):
  - The README states that night (211) "is absent from every sample". In fact 78 night pixels occur in 4 samples: h12v03 2023-12-15 (72), h20v02 2024-02-15 (3), h21v02 2024-02-15 (2) and h21v02 2024-04-15 (1).
  - The `select_plan.py` docstring calls h20v02 "Fennoscandia". It is the northern Urals/Pechora, as the README says correctly.
