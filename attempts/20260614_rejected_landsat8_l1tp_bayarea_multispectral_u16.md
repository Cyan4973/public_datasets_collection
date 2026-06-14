# Rejected: landsat8_l1tp_bayarea_multispectral_u16

- Date: 2026-06-14
- Candidate: `staging/landsat8_l1tp_bayarea_multispectral_u16`
- Domain: satellite imagery / native UInt16 GeoTIFF rasters
- Intended natural sample: one source GeoTIFF band raster
- Intended primary payload: selected Landsat 8 Level-1 UInt16 bands from one bounded scene

## Decision

Rejected before download/build validation.

## Reason

The recipe required GDAL command-line tools (`gdalinfo`, `gdal_translate`) to inspect and decode GeoTIFF rasters. Those tools are not available through the local `feature` mechanism, and relying on system package installation makes the recipe too environment-specific for this collection.

## Retry Conditions

Retry only if the build path can be made locally reproducible with standard repository-supported tooling, for example:

- a portable decoder bundled through an accepted local feature,
- a pure standard-library parser for the specific uncompressed TIFF shape,
- or a different upstream 16-bit raster source that is already raw or trivially decoded without specialized GIS dependencies.
