# NASA PDS THEMIS IR Mosaic Int16

Rejected/guarded staging recipe for selected Mars THEMIS controlled IR mosaic resources from USGS Astropedia/PDS.

Run:

```bash
staging/nasa_pds_themis_ir_mosaic_i16/download.sh
```

The tested default controlled-mosaic products are native unsigned 8-bit rasters, not 16-bit products. The script now downloads small labels first and fails unless a selected product label proves native 16-bit samples before any large image payload is downloaded.
