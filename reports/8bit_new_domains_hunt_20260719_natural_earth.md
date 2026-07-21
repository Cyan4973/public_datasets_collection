# 8-Bit New-Domain Hunt: Natural Earth Vector Shapefile Geometry

## Superseded

Do not run the staged recipe `natural_earth_vector_shp_u8`. It was rejected on
2026-07-21 because it treated whole Shapefile containers as `uint8` primary
series. Use the decoded successor `natural_earth_10m_geometry_xy_f64` instead.

## Original Recommendation

## Why This Adds New Territory

- Domain: public-domain cartographic vector geometry.
- Shape: one ESRI Shapefile `.shp` geometry stream per coherent Natural Earth
  10m layer.
- Difference from accepted datasets: the catalog has geospatial rasters,
  building-footprint geometry, road edges, point gazetteers, and OSM metadata,
  but not source shapefile geometry byte streams from a cartographic atlas.
- Numeric representation: source `.shp` geometry payloads are emitted unchanged
  as uint8 byte arrays after ZIP and shapefile-header validation.

## Materiality

An older local benchmark for this staging recipe measured 12 primary samples and
96,390,016 primary uint8 values/bytes. The Natural Earth S3 URLs checked in this
pass are reachable and range from about 3 MB to 15 MB for representative ZIP
files, so the selected layer set remains safely below the repository's 1 GB
per-dataset cap while being large enough to deserve collection.

The recipe enforces:

- at least 10 shapefile samples
- valid ESRI shapefile headers
- non-degenerate byte payloads
- non-identical sample sizes
- median sample size above 1,000 bytes
- primary-output hard cap: 1,000,000,000 bytes

## Script To Run

Do not run the original staged script. The recipe has been rejected and the
staging copy has been removed.

## Rejected Candidates In This Pass

- Noto/Google font packages would add typography/font-program bytes, but the
  Google Fonts and Noto package endpoints returned 403 in this environment.
- USPTO patent bulk ZIPs would add patent-document text/XML bytes, but the
  official bulk-data host returned 502 through the proxy.
- Wikimedia pages-articles XML shards would add encyclopedia UTF-8 article
  bytes, but `dumps.wikimedia.org` returned 403.
- More Open Images annotation or segmentation material was avoided because the
  collection already has Open Images bounding-box annotations and multiple mask
  or segmentation datasets.

## Historical Acceptance Outcome

This outcome was later overturned by the 2026-07-21 opaque-container cleanup.
The byte recipe is rejected and superseded by
`natural_earth_10m_geometry_xy_f64`.

Accepted after user download and local processing.

- Downloaded 12 Natural Earth 10m vector ZIPs.
- Emitted 12 primary uint8 samples from validated `.shp` geometry streams.
- Total primary values/bytes: 96,390,016.
- Sample byte-size range: 25,104 min / 6,986,842 median / 23,766,908 max.
- Every emitted sample reached 256 distinct byte values.
