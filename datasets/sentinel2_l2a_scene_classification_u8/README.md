# Sentinel-2 L2A Scene Classification (u8)

Accepted `uint8` recipe for the Sentinel-2 Level-2A Scene Classification Layer
(`SCL`) from public Element84 Cloud Optimized GeoTIFFs.

This is not GeoTIFF byte preservation. The build parses each local TIFF,
decompresses the SCL raster tiles, validates official class-code values, and
emits one raw `uint8` raster sample per source scene.

## Run

```bash
bash datasets/sentinel2_l2a_scene_classification_u8/download.sh
bash datasets/sentinel2_l2a_scene_classification_u8/build.sh
bash datasets/sentinel2_l2a_scene_classification_u8/verify.sh
```

The default source download is small because SCL COGs compress heavily, but the
decoded primary payload is 60,280,200 bytes across two full 20 m scene
classification rasters.
