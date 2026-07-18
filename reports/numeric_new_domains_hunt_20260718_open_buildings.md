# Numeric New Domains Hunt: Google Open Buildings Footprint Geometry

## Recommendation

Stage `google_open_buildings_v3_s2_073_geometry_f32`, using one fixed public Google Open Buildings v3 S2 level-4 gzip CSV tile.

## Why This Adds New Territory

- Domain: built-environment building-footprint geometry extracted from satellite imagery.
- Shape: hundreds of thousands to millions of building rows with centroids, footprint areas, confidence scores, and polygon vertices.
- Difference from accepted datasets: the catalog has point gazetteers, road edges, GTFS shapes, LiDAR classifications, and image/annotation data, but not large building-footprint polygon geometry.
- Numeric representation: source decimal centroid, area, confidence, and WKT polygon vertex coordinates are emitted as float32 streams; plus codes and text fields are excluded.

## Materiality

The selected public object, `073_buildings.csv.gz`, is about 139 MB compressed. It should produce tens to hundreds of MB of primary geometry data while remaining well under the repository's 1 GB per-dataset cap.

The recipe enforces:

- source download hard cap: 1,000,000,000 bytes
- default source download cap: 800,000,000 bytes
- download row floor: 500,000 source rows
- build floor: 500,000 buildings
- polygon vertex floor: 2,500,000 vertex pairs
- verify value floor: 8,000,000 values
- verify primary-byte floor: 32,000,000 bytes
- primary-output hard cap: 1,000,000,000 bytes

## Script To Run

```bash
bash staging/google_open_buildings_v3_s2_073_geometry_f32/download.sh
```

After the download succeeds, build and verify locally:

```bash
bash staging/google_open_buildings_v3_s2_073_geometry_f32/build.sh
bash staging/google_open_buildings_v3_s2_073_geometry_f32/verify.sh
```

## Rejected Candidate In This Pass

- BLS QCEW annual single-file data would have added regional labor-market microaggregates, but `data.bls.gov` is blocked from this environment.

## Acceptance Outcome

The Open Buildings v3 S2 073 tile downloaded, built, and verified successfully.

- source gzip bytes: 139,127,240
- source rows/buildings: 1,449,095
- polygon vertex pairs: 7,750,581
- primary samples: 4
- primary values: 21,297,542
- primary bytes: 85,190,168
- output cap behavior: full tile processed; no truncation
- geometry handling: accepted both `POLYGON` and `MULTIPOLYGON` WKT and emitted all parsed lon/lat vertex pairs in source order
