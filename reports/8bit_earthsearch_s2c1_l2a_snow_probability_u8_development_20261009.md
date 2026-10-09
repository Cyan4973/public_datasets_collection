# Sentinel-2 Collection-1 L2A Sen2Cor snow-probability uint8 development

## Outcome

Accepted `earthsearch_s2c1_l2a_snow_probability_u8`: 30 complete 5490x5490 Sen2Cor snow-probability grids (percent 0-100, 20 m). They come from Sentinel-2 Collection-1 Level-2A products on 30 distinct MGRS tiles, acquired March-April 2024, and are decoded from Element84 Earth Search COGs into raw uint8.

This family is distinct from the accepted `sentinel2_l2a_scene_classification_u8`. That recipe holds two SCL class-code rasters from the old `sentinel-cogs` L2A archive. This recipe holds the continuous `MSK_SNWPRB_20m` probability layer from the Collection-1 reprocessing (the `snow` asset, `SNW_20m.tif`). The nearest family by bytes is `mpc_modis_mod10a1_ndsi_snow_cover_u8`. The two are compression-equivalent (loss 0.0) but not feature-close (distance 0.0688 against the 0.05 threshold), so the measured verdict is OK. The material is also different in kind: a 20 m Sen2Cor snow probability with no in-band flag codes, against a 500 m MODIS NDSI x 100 with flag codes 200-255.

## Source and rights

- Source: Earth Search collection `sentinel-2-c1-l2a`, processing baseline 05.10 only. Objects are in the public anonymous bucket `e84-earth-search-sentinel-data` (us-west-2, not requester-pays).
- Pinned objects: 30 `SNW_20m.tif` COGs, 274,844,184 bytes in total (2,793,235 to 16,329,425 each). Each has an exact size and a SHA-256 from the STAC `file:checksum` multihash, both recorded in `sources.tsv`.
- License: "Legal notice on the use of Copernicus Sentinel Data and Service Information" (EU Delegated Regulation 1159/2013). It grants free use for "(a) reproduction; (b) distribution; (c) communication to the public; (d) adaptation, modification and combination with other data". For modified data it requires the notice "Contains modified Copernicus Sentinel data [Year]". The STAC collection links this notice as `rel=license`. The recipe's attribution is "Contains modified Copernicus Sentinel data 2024."
- No credentials, no personal data.

## Shape and conversion

- **Natural record:** one SNW_20m COG per Sentinel-2 L2A product, which is one MGRS tile acquisition. Its IFD0 is the full 5490x5490 grid; the overview IFDs are ignored.
- **Decode:**
  - Read IFD0 of each classic little-endian TIFF: 8-bit unsigned, 1 sample, Deflate, predictor 2, 121 tiles of 512x512.
  - Inflate each tile and undo predictor 2 as a running byte sum modulo 256 along each tile row.
  - Crop the padded edges (5490 = 10x512 + 370) and write the grid row-major (y, x).
  - Values are not changed. The GDAL metadata declares no scale or offset.
- **Missing values:** GDAL nodata is 0, which is the same code as 0 % snow. Only scenes with `s2:nodata_pixel_percentage == 0` were selected, so there is no swath-edge fill and every 0 is kept as a measured 0 %.
- **Selection rule** (deterministic, documented in `scripts/discover.py` and `scripts/select_plan.py`):
  1. STAC query: 2024-03..04, `eo:cloud_cover < 15`, `nodata_pixel_percentage == 0`, `25 <= snow_ice_percentage <= 75`. This returns 1,785 items on 1,184 tiles.
  2. Keep one scene per tile.
  3. Group tiles into cells of 10 deg latitude x 20 deg longitude. Within a cell, pick the tile whose header nonzero share is closest to 0.5.
  4. Take the 30 most populated cells.
- **Realized scope:** Northern Hemisphere only, 29.3-61.7 N; platforms S2A and S2B; one baseline. The README and manifest claim exactly this.

## Accepted output

| Item | Value |
|---|---|
| Primary samples | 30, one series: `s2c1_l2a_snw_20m_snow_probability_u8` |
| Sample size | 30,140,100 values each (5490x5490) |
| Primary values and bytes | 904,203,000 (uint8) |
| Value range | 0..100; every grid uses all 101 values |
| Share of value 0 | 0.473 / 0.514 / 0.579 (min / median / max) |
| Share of value 100 | 0.126 / 0.362 / 0.487 |
| Share of values 1-99 | 0.025 / 0.118 / 0.361 |
| Largest mode share | 0.579 |
| Duplicate grids | none |
| Aggregate decoded SHA-256, in `sources.tsv` order | `48adb103e12b48082336830a56db33537e3d06cbece257f5499f0dcd30e38417` |

## Judge checks

- **Mechanics:** `gate.py` PASS with no warnings (values = bytes = 904,203,000; 30 samples; median 30,140,100; width 8).
- **Reproducibility:**
  - I ran `verify.sh` myself and it passed in 90 s. It re-decodes all 30 sources with separate code and matches the samples byte-for-byte. It also checks the GDAL header statistics (nonzero % within 0.005, nonzero mean within 1e-6), the index, and the manifest totals.
  - `build.sh` reads only `.data/downloads`, after a synthetic decoder self-test.
  - The driver's download log shows 30/30 fetched and SHA-256 and layout validation passed.
- **Bytes:** I inspected all 30 grids with standard-library scripts.
  - No value above 100.
  - The 1-99 band is continuous and grows toward 100. Values 1-12 are rare, which is a known Sen2Cor shape, not a decode artifact.
  - zlib ratio is 0.05-0.34 and the horizontal transition rate is 0.045-0.40, so the grids have real spatial structure.
  - No tile-seam discontinuity: mean |delta| across x and y multiples of 512 matches mid-tile values. The cropped last row and column are continuous with their neighbours.
  - A downsampled map of T44RKV shows coherent Himalayan snow over high ground and none on the southwestern plain.
  - IFD0 tags show no scale or offset.
- **Rights:** I fetched the STAC collection: `rel=license` points to the Sentinel Data Legal Notice. I read the notice PDF from sentinels.copernicus.eu and confirmed the grants and the attribution wording. A credential grep found nothing.
- **Novelty:**
  - `novelty.py` finds no recipe, registry row, ledger entry or downstream family for SNW, SNWPRB or snow probability.
  - The only URL match is this staging recipe itself. `sentinel2_l2a_reflectance_cogs_u16` shares only the STAC host and uses the old `sentinel-cogs` archive.
  - Same-type neighbours are MODIS NDSI, IMS snow and SCL. None is the same source file or asset.
  - Driver zlsim verdict: OK.
- **Homogeneity:** one quantity (Sen2Cor snow probability %), one collection and baseline, one 20 m MGRS tile grid, one season window. S2A and S2B are the same product line.
- **Volume:** 30 natural 30 MB records is the most that fits under the 1 GB cap. The population is about 1,184 tiles, so the cap is the binding limit, not the floor. The 3.3x extraction ratio is because Deflate compresses the long runs of 0 and 100; nothing is thrown away.
- **Caveats** (accepted as properties of the material):
  - Strong bimodality.
  - The selection targets scenes about 50 % snow-covered so that grids are not all zeros.
  - Narrow feature margin to MODIS NDSI.
