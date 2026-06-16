# Sentinel-2 L2A Reflectance COG Uint16

Bounded Sentinel-2 Level-2A surface-reflectance Cloud Optimized GeoTIFF recipe using the Element84 public `sentinel-cogs` bucket.

Run:

```bash
datasets/sentinel2_l2a_reflectance_cogs_u16/download.sh
datasets/sentinel2_l2a_reflectance_cogs_u16/build.sh
datasets/sentinel2_l2a_reflectance_cogs_u16/verify.sh
```

The default selection targets two low-cloud scenes and three native reflectance bands per scene: one 10 m band, one 20 m band, and one 60 m band. Each natural sample is one source band raster. The build decodes compressed/tiled TIFF losslessly into raw native uint16 pixel planes without resampling, band stacking, or scene concatenation.
