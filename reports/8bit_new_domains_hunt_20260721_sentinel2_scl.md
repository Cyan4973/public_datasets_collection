# 8-Bit New-Domain Hunt: Sentinel-2 Scene Classification

## Recommendation

Run the staged recipe `sentinel2_l2a_scene_classification_u8`.

```bash
bash staging/sentinel2_l2a_scene_classification_u8/download.sh
```

## Why This Adds New Territory

- Domain: satellite scene-quality / surface-category classification.
- Primary target: Sentinel-2 Level-2A `SCL` band values, decoded from GeoTIFF to
  source-native `uint8` class-code rasters.
- Difference from existing datasets: the catalog already has Sentinel-2
  reflectance as `uint16`, ESA static land cover, and JRC water occurrence. SCL
  is per-scene atmospheric/surface classification, not reflectance, static land
  cover, or file bytes.
- Natural sample: one full source `SCL.tif` scene-classification raster.

## Materiality

The default plan uses two exact Element84 Sentinel-2 COG S3 objects already
aligned with scenes used by the accepted Sentinel-2 reflectance recipe:

- `S2B_11SKB_20230812_0_L2A/SCL.tif`
- `S2B_19KDP_20230814_0_L2A/SCL.tif`

The compressed downloads are expected to be small because categorical SCL rasters
compress heavily, but the decoded primary output should be about 60 MB across two
full 20 m rasters. Verification requires valid `uint8` TIFF metadata, official
SCL class codes `0..11`, nonconstant rasters, natural scene-level samples,
primary bytes below 1 GB, and no GeoTIFF/container bytes as primary data.

## Notes

The script avoids live STAC because the current agent network path blocks the
Element84 search API. It uses exact public S3 asset URLs and the build performs
pure-Python TIFF tile decoding with `zlib`/LZW support.

## Outcome

Accepted and promoted to `datasets/sentinel2_l2a_scene_classification_u8`.

- Downloaded source bytes: 560,263 across two fixed `SCL.tif` COGs.
- Decoded primary payload: 2 samples, 60,280,200 `uint8` values/bytes.
- Natural sample size: 30,140,100 values per full 5490x5490 SCL raster.
- Validation: both samples contain only official SCL class codes `0..11`, are
  nonconstant, and preserve scene-level sample boundaries.
