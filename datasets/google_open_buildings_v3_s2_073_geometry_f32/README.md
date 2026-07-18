# Google Open Buildings V3 S2 073 Geometry Float32

This staging recipe collects one public Google Open Buildings v3 S2 level-4 gzip CSV tile and emits built-environment footprint geometry streams.

The domain is global building-footprint extraction from satellite imagery. The source rows contain a centroid, area, confidence score, plus code, and WKT polygon. The build excludes plus codes and other text, and emits:

- building centroid latitude/longitude pairs as float32
- building footprint area as float32
- model confidence as float32
- polygon vertex longitude/latitude pairs as float32

Run:

```bash
bash staging/google_open_buildings_v3_s2_073_geometry_f32/download.sh
bash staging/google_open_buildings_v3_s2_073_geometry_f32/build.sh
bash staging/google_open_buildings_v3_s2_073_geometry_f32/verify.sh
```

The default source object is `v3/polygons_s2_level_4_gzip/073_buildings.csv.gz`, about 139 MB compressed. The scripts enforce hard 1 GB source and primary-output caps.
