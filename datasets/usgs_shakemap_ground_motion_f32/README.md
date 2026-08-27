# USGS ShakeMap Ground-Motion Float32

This accepted recipe targets official USGS ShakeMap raster products for significant
earthquakes. The desired primary arrays are physical ground-motion and hazard
fields such as peak ground acceleration (PGA), peak ground velocity (PGV),
Modified Mercalli Intensity (MMI), and spectral acceleration.

Each retained layer would be one complete two-dimensional earthquake map. This
is distinct from accepted seismic waveform traces and scalar earthquake catalog
columns: the values form spatially correlated hazard fields with source-
distance attenuation, directional structure, site effects, sharp coast/mask
boundaries, and event-specific geometry.

The discovery step queries only official USGS earthquake and product metadata.
It selects significant events whose detail records expose a preferred ShakeMap
`raster.zip` product and records its exact URL, size, product code, source, and
update time. It does not download any raster archive.

Run from the repository root:

```bash
bash staging/usgs_shakemap_ground_motion_f32/discover.sh
```

Results are written to
`.data/discovery/usgs_shakemap_ground_motion_f32/candidates.tsv`, with exact
event detail metadata in the adjacent `events/` directory. Before acquisition,
the selected archives must still be checked for GeoTIFF member names, native
float32 sample format, compression, dimensions, NoData semantics, physical
units, byte volume, and layer duplication. Integer-coded, rendered-image, or
float64-only products will not qualify for this family.

Discovery found 99 bounded products. The first technical probe selects the
current USGS-produced ShakeMap for the 2025 M8.8 Kamchatka Peninsula earthquake
(`us6000qw60`). Its version-pinned `raster.zip` is 13,201,579 bytes. This avoids
starting with older Atlas reprocessings while providing a large, authoritative
event likely to contain all standard ground-motion layers.

Download the exact event metadata, official USGS public-domain statement, and
raster archive, then inspect its member schemas with:

```bash
bash staging/usgs_shakemap_ground_motion_f32/download.sh
```

The preflight confirmed fourteen native little-endian float32 ESRI BIL rasters:
MMI, PGA, PGV, and four PSA periods, each with mean and standard-deviation
layers. All share a 496x795 grid, contain no declared NoData value, and are
nonconstant and byte-distinct.

Build and independently verify them with:

```bash
bash staging/usgs_shakemap_ground_motion_f32/build.sh
bash staging/usgs_shakemap_ground_motion_f32/verify.sh
```

The result contains 5,520,480 native float32 values and 22,081,920 bytes. MMI
is retained in linear intensity units. PGA, PGV, and PSA means remain in their
source natural-log representation, with uncertainty layers retained as source
log-sigma values; the recipe does not exponentiate or otherwise transform the
published words.
