# Statlog (Landsat Satellite) Spectral DN (uint8)

Collects **Landsat MSS multispectral surface-reflectance digital numbers** (0–255)
from the [UCI *Statlog (Landsat Satellite)*](https://archive.ics.uci.edu/dataset/146/statlog+landsat+satellite)
dataset — a small sub-scene of a Landsat Multispectral Scanner image, imaged in
four spectral bands.

Each upstream row is a 3×3 pixel neighbourhood: 36 attributes (9 pixels × 4 bands,
stored pixel-major) plus a class label. We regroup by **band** — the natural
coherent quantity — so each band becomes one `uint8` series carrying its per-pixel
reflectance DN values in row order. The four bands:

| Series | Band | Approx. wavelength |
| --- | --- | --- |
| `landsat_band_green_u8` | green | ~0.5–0.6 µm |
| `landsat_band_red_u8` | red | ~0.6–0.7 µm |
| `landsat_band_nir1_u8` | near-infrared 1 | ~0.7–0.8 µm |
| `landsat_band_nir2_u8` | near-infrared 2 | ~0.8–1.1 µm |

This fills a genuine local gap: the corpus has Mars thermal-IR (`nasa_pds_themis_ir_mosaic_u8`),
land-cover *class* labels (`esa_worldcover_landcover_tiles_u8`), but no
**optical satellite reflectance**. The retired `noaa_nexrad_level3_products_u8`
recipe is not counted as coverage because it preserved product-message bytes
instead of decoded radar values. The DN values here are the sensor's *native*
8-bit representation (not a width mirror). The trailing class label is
categorical metadata and is **not** collected.

## Usage

```bash
datasets/statlog_landsat_satellite_u8/download.sh
datasets/statlog_landsat_satellite_u8/build.sh
datasets/statlog_landsat_satellite_u8/verify.sh
```

The downloader fetches the pinned UCI static zip and, if that is unavailable,
falls back to the classic `ml-databases/statlog/satimage/{sat.trn,sat.tst}`
directory (identical files). It rejects semantically invalid payloads (wrong
token count, non-integer tokens, attributes outside 0–255, labels outside 1–7),
so an HTML error page or truncated file fails the download rather than building.

Optional overrides: `STATLOG_ZIP_URL`, `STATLOG_DIRECT_BASE`.

## Structure

The upstream `sat.trn` / `sat.tst` split is the natural file boundary, so each
band emits **one sample per file** (no cross-file concatenation): 4 bands × 2
files = **8 samples**, ~226 KB, **231,660** genuine uint8 DN values total. Values
are serialized in row order with each row's nine per-band pixels contiguous,
preserving 3×3 spatial locality.
