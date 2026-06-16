# NASA PDS THEMIS IR Mosaic Uint8

Selected Mars THEMIS controlled thermal-infrared mosaic rasters from USGS Astropedia/PDS.

Run:

```bash
datasets/nasa_pds_themis_ir_mosaic_u8/download.sh
datasets/nasa_pds_themis_ir_mosaic_u8/build.sh
datasets/nasa_pds_themis_ir_mosaic_u8/verify.sh
```

The recipe keeps a bounded two-mosaic subset so primary output remains under 1 GB. Each natural sample is one source mosaic image; the build extracts the native uncompressed single-band uint8 pixel plane from the TIFF without resampling or concatenating images. The selected direct TIFF URLs were discovered from the Astropedia product pages, and the related PDS/ISIS labels identify these products as unsigned 8-bit rasters.
