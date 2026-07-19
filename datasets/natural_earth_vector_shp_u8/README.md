# Natural Earth Vector Shapefile Geometry Bytes (uint8)

This recipe downloads selected Natural Earth public-domain vector layers
and emits one raw uint8 sample per source `.shp` geometry file.

The natural sample is the ESRI Shapefile geometry stream for one coherent layer.
The build validates the shapefile header and copies `.shp` bytes unchanged.
