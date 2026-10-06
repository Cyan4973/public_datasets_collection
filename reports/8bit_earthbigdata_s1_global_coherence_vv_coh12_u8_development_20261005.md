# Sentinel-1 global seasonal VV COH12 coherence uint8 development

## Outcome

Accepted `earthbigdata_s1_global_coherence_vv_coh12_u8`. It is the first interferometric-coherence (InSAR) family in the local or downstream corpus.

The existing SAR families (`sentinel1_grd_measurement_u16`, `nasa_pds_cassini_radar_bidr_sigma0_u8`, and downstream `sentinel1_grd_hh_dn_u16`) all store backscatter amplitude. This family stores the magnitude of the complex correlation between repeat-pass acquisitions 12 days apart, which is a different physical quantity. Novelty kind: new quantity.

## Source and rights

- **Source:** the Global Seasonal Sentinel-1 Interferometric Coherence and Backscatter Data Set (Earth Big Data LLC and Gamma Remote Sensing AG, for NASA JPL).
  - Hosted in the AWS Open Data bucket `sentinel-1-global-coherence-earthbigdata` (us-west-2), with anonymous HTTPS access and no requester-pays.
  - Bucket documentation is dated 2021-09-08 (Kellndorfer and Cartus).
- **Objects:** 150 files of the form `data/tiles/<TILE>/<TILE>_summer_vv_COH12.tif`, all with Last-Modified 08 Sep 2021.
  - Size and single-part ETag MD5 of each file are pinned in `sources.tsv`.
  - Total: 161,185,497 bytes, 865,142 to 1,209,506 per file.
- **License: CC BY 4.0.**
  - The bucket's own `index.html` says: "The use of these data fall under the terms and conditions of the Creative Commons Attribution 4.0 International Public License Contains modified Copernicus Sentinel data."
  - The Earth Engine catalog entry `Earth_Big_Data_GLOBAL_SEASONAL_S1_V2019_COHERENCE` lists Terms of Use CC-BY-4.0.
- **Citation:** Kellndorfer, J., Cartus, O., Lavalle, M. et al., Sci Data 9, 73 (2022), doi:10.1038/s41597-022-01189-6, plus the Copernicus attribution.

## Shape and conversion

Each natural record is one producer 1×1° tile GeoTIFF for one metric: 1200×1200 single-band uint8 at 3 arcseconds, rows north to south. One tile becomes one sample. Tiles are neither cut up nor merged.

- **Scaling:** the producer documents coherence as γ = DN/100, nodata 0, stored as unsigned 8-bit.
- **Scope:**
  - Only `summer_vv_COH12` is used: the JJA 2020 median of all 12-day repeat VV coherence estimates.
  - Other seasons, HH, the other temporal baselines (COH06/18/24/36/48), AMP backscatter, rho/tau/rmse decay parameters, and the inc/lsmap layers are never downloaded.
- **Block:** upper-left labels N36..N45 × W100..W114, i.e. 35–45°N, 114–99°W. It covers the interior western US: Great Basin and Colorado Plateau desert, Rocky Mountain forest, sagebrush steppe, and High Plains dryland and irrigated cropland.
- **Decode:**
  1. Parse the classic little-endian TIFF IFD with `struct`.
  2. Check the pinned layout: LZW, Predictor 1, 200 strips of 6 rows, GDAL_NODATA "0", 1/1200° pixel scale, and a tiepoint equal to the tile corner.
  3. LZW-decode each strip with a pure-Python TIFF-LZW decoder (MSB-first, early change). Each strip must decode to exactly 7,200 bytes ending in an EOI code.
  4. Join the strips in order and write the DNs unchanged, with nodata 0 kept in place.
- **Rejection rules (build and verify):** a tile fails if it is all nodata, more than 50% nodata, has fewer than 3 distinct DNs, contains any DN above 100, or duplicates another raster.

## Accepted output

- Primary samples: 150
- Primary values and bytes: 216,000,000 (uint8)
- Sample size: 1,440,000 values each, which is also the minimum, median and maximum
- DN range: 1..100 overall, with 90–100 distinct values per tile
- Global quantiles: 1% = 4, 25% = 30, median = 48, 75% = 66, 99% = 88
- Nodata (DN 0): 297,288 pixels (0.138%) in 33 tiles
  - Largest: N37W102 at 12.3% and N38W102 at 7.8%
  - Every other tile is below 0.5%
- Per-tile mean DN: 15.6 (N45W100) to 80.5 (N40W114); the mean of tile means is 47.4 with standard deviation 15.2
- Aggregate SHA-256 of per-sample SHA-256s: `a4903510d0d9933dab2ca2e859f7afb67cd64017d0906e8b45f289483a230828`

The local build and the byte-for-byte re-decode in verify both succeeded against the pinned downloads.

## Judge checks

- **Gate:** `gate.py` passes with no warnings (values = bytes = 216,000,000, 150 samples, median 1,440,000, width 8).
- **Verify:** I ran `verify.sh` myself and it exited 0: `verify_ok samples=150 bytes=216000000 nodata_fraction=0.001376 dn_range=1..100 distinct=100`.
- **Local-only build:** `s1coh.py` has no network imports and reads only `.data/downloads/<id>/tiles/`.
- **Independent decoder:** the system libtiff 5 (`/lib64/libtiff.so.5`, called through ctypes under `/usr/bin/python3.9`, `TIFFReadEncodedStrip`) decodes all 150 source tiles byte-identically to the emitted samples. This checks the builder's own LZW code against the reference C implementation.
- **IFD dump:** I dumped the IFD of N40W105 and N37W102 with `struct`. Each has a single IFD, no overviews, and no GDAL scale/offset metadata. The layout matches the manifest.
- **Distribution:** the histogram is smooth and unimodal, with no gaps, no DN above 100, and natural tails at both ends.
- **Texture:** speckle-like, with mean |dx| of 1.9–3.9 and a zlib-9 ratio of 1.5–1.9.
- **Seams:** the 140 east–west tile boundaries have no identical edge columns, and the mean edge |diff| of 3.33 is close to the 3.16 between interior adjacent columns. So the mosaic is seamless with no duplicated overlap.
- **No near-duplicates:** comparing 20,000 sampled pixels across all tile pairs, the closest pair still differs in 19,165.
- **Rights:** I read the license on the bucket `index.html` and on the Earth Engine catalog page for the COHERENCE product myself. The AWS registry page and GitHub are blocked by the proxy. The scripts contain no credentials.
- **Novelty:** `novelty.py` (bucket URL plus coherence, interferometric, insar, earthbigdata, kellndorfer, COH12) finds only this candidate. Downstream 8-bit and transformer listings contain no coherence material.
- **Caveats:**
  - The values come from a processed seasonal-median product, but the uint8 storage is the producer's own.
  - Only about 7 of the 8 bits are used.
  - The block covers one region, so diversity comes from land cover, not from global sampling.
  - The builder fetched two full tiles (about 2 MB) to `/tmp` during authoring, which goes slightly beyond metadata probes. It has no effect on the recipe.
