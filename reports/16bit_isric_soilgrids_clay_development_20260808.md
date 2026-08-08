# ISRIC SoilGrids clay-content int16 development — 2026-08-08

## Outcome

Accepted `isric_soilgrids_clay_i16`: 256 complete native signed-int16
SoilGrids mean clay-content raster tiles for the 0–5 cm surface-soil layer.

## Domain and shape distinction

This is the corpus's first pedology and modeled soil-composition family. It
adds environmental surface-property fields with broad smooth regions, local
gradients, geographic boundaries, coastline/nodata structure, and fixed
two-dimensional 450×450 samples. It is distinct from elevation, weather,
satellite reflectance, microscopy, and synthetic material-displacement maps.

## License and source

ISRIC's official SoilGrids page explicitly states that SoilGrids data are
publicly available under the Creative Commons Attribution 4.0 License. The
manifest preserves the SoilGrids 2.0 paper citation and DOI.

The official clay 0–5 cm mean VRT declares a global Interrupted Goode
Homolosine mosaic with:

- one signed `Int16` band
- explicit nodata value `-32768`
- 159,246 by 58,034 global VRT cells
- 12,970 source TIFFs
- 10,169 complete 450×450 TIFFs

The 5,929,079-byte VRT snapshot has SHA-256
`ad1a77d56090bf543e3600bc48d4cd6fa80f8e1a9eb37177044de65a64848ede`.

The selection applies deterministic farthest-point coverage to normalized VRT
tile centers and retains 256 geographically dispersed complete tiles. It does
not inspect cell values when choosing sources.

Every selected URL, VRT offset, byte size, and SHA-256 is pinned in
`sources.tsv`.

## Native type and decoding

Representative license-first preflight and all downloaded files establish a
uniform simple TIFF layout:

- classic TIFF with little-endian byte order
- one signed 16-bit sample per pixel
- 450 rows by 450 columns
- uncompressed strips, nine rows per strip
- no horizontal predictor
- `-32768` GDAL nodata declaration

The dependency-free decoder reconstructs all IFD fields and external arrays,
validates 50 non-overlapping strip offsets and byte counts, and concatenates
the unchanged strip bytes in row order. Because the stored byte order is
already canonical little-endian, no numeric or byte transformation is needed.
Physical scaling and reprojection are deliberately excluded.

## Accepted material

- 256 complete fixed-shape raster samples
- 202,500 signed-int16 values per sample
- 51,840,000 total values
- 103,680,000 primary bytes
- 43,936,753 valid clay-content cells
- 7,903,247 preserved nodata cells (15.25%)
- valid stored-code range 7 through 651
- 80–479 distinct values per tile
- 17,267–194,342 adjacent-value transitions per tile
- 40,228,472 adjacent-value transitions overall
- all 256 output hashes unique

Independent verification rechecks all source hashes and TIFF invariants,
regenerates every row-major little-endian byte stream, and compares every
output byte, sample-index row, and aggregate statistic.

## Safety

The source contains modeled environmental soil properties, not personal,
human-subject, or identifying data. SoilGrids is a global prediction product;
ISRIC cautions users to apply it carefully for local-scale decisions.
