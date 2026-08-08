# ISRIC SoilGrids clay-content int16

This recipe collects 256 geographically dispersed complete 450×450 native
signed-int16 tiles from the official SoilGrids mean clay-content map for the
0–5 cm soil layer. One complete GeoTIFF source is one raster sample.

Run:

1. `bash datasets/isric_soilgrids_clay_i16/download.sh`
2. `bash datasets/isric_soilgrids_clay_i16/build.sh`
3. `bash datasets/isric_soilgrids_clay_i16/verify.sh`

The source plan pins every URL, size, SHA-256, and global VRT offset. The
dependency-free decoder accepts only classic little-endian TIFF with one
signed-int16 band, no compression or predictor, the declared `-32768` nodata
value, and exact 450×450 row-strip geometry. It copies all stored cell words in
row-major order without scaling or reprojection. Verification independently
decodes and compares every output byte and metadata record.
