# Sentinel-2 L2A Reflectance COG Uint16

Bounded Sentinel-2 Level-2A surface-reflectance Cloud Optimized GeoTIFF recipe using the Element84 public `sentinel-cogs` bucket.

Run:

```bash
datasets/sentinel2_l2a_reflectance_cogs_u16/download.sh
datasets/sentinel2_l2a_reflectance_cogs_u16/build.sh
datasets/sentinel2_l2a_reflectance_cogs_u16/verify.sh
```

The default selection targets two low-cloud scenes and three native reflectance
bands per scene: one 10 m band (`blue_10m`), one 20 m band (`rededge1_20m`), and
one 60 m band (`coastal_60m`). These are one homogeneous family of uint16 surface
reflectance.

The natural sample boundary is one **native COG internal tile**, not a whole band
raster. A single 10 m band is a ~240 MB image, far too large for a training
sample, so each band contributes many native tiles instead. Element84 COGs are
internally tiled at the band's resolution — blue 1024², red-edge 512², coastal
256² — so each sample is one such tile, decoded exactly once (Deflate via `zlib`,
with predictor=2 horizontal differencing reversed losslessly). Sentinel-2 MGRS
tiles carry large nodata borders stored as zeros; the build keeps only full
interior tiles that are non-constant and at least 98% in-swath, dropping the
nodata border. Two default scenes yield roughly 72 tiles (~80 MB) across the
three bands.

Tunables (all optional):

| Variable | Default | Meaning |
| --- | --- | --- |
| `SENTINEL2_MIN_NONZERO_FRACTION` | `0.98` | Minimum in-swath (non-zero) fraction per tile |
| `SENTINEL2_MAX_TILES_PER_BAND` | `0` | Per-(scene, band) tile cap (`0` = unlimited) |
| `SENTINEL2_MIN_SAMPLE_COUNT` | `12` | Minimum tiles required for the build to succeed |

The build performs only lossless TIFF decompression and predictor reversal — no
resampling, band stacking, or scene concatenation.
