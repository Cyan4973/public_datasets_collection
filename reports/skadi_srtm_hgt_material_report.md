# Skadi SRTM HGT Material Report

Validated on 2026-06-16 after repairing the accepted recipe to preserve the
natural HGT tile boundary.

## Scope And Source

- Dataset: `skadi_srtm_hgt`
- Tile: `N37W122`
- Source URL:
  `https://s3.amazonaws.com/elevation-tiles-prod/skadi/N37/N37W122.hgt.gz`
- Source gzip bytes: `10,093,110`
- Decoded HGT bytes: `25,934,402`
- Decoded shape: `3601 x 3601`

## Accepted Output

- Status: `ok`
- Primary samples: `1`
- Primary values: `12,967,201`
- Primary bytes: `25,934,402`
- Median primary sample values: `12,967,201`
- Sample geometry: `2d_raster`
- Sample shape: `[3601, 3601]`
- Sample axes: `["y", "x"]`
- Sample SHA256: `9fa86b9dc97710bd2607d89f23ef6c8001b31c52652dcc11175864e02d930c92`

| series_id | role | kind | values | bytes | min | p10 | median | p90 | max | distinct |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `skadi_elevation` | primary | int16 | 12,967,201 | 25,934,402 | -25 | 7 | 170 | 689 | 1,332 | 1,341 |

## Repair Notes

The earlier accepted recipe split the same `N37W122` tile into `67` row-band
samples. That was not the natural sample boundary. The repaired recipe emits
one whole-tile sample and marks it as a 2D raster in the sample index.

The temporary `skadi_srtm_bay_area_hgt_i16` staging recipe was the same tile
and has been removed to avoid duplicate dataset identity.

## Validation

- `datasets/skadi_srtm_hgt/build.sh` completed locally.
- `datasets/skadi_srtm_hgt/verify.sh` completed locally.
- `reports/accepted_recipe_audit.tsv` classifies `skadi_srtm_hgt` as `ok`.
- `reports/skadi_srtm_hgt_state.md` and
  `reports/skadi_srtm_hgt_state.tsv` contain the generic sample-size state
  report.
