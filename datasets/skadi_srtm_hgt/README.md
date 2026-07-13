# Skadi SRTM HGT

Exact-ID backfill for the external `skadi_srtm_hgt` reference.

The repaired recipe preserves the natural sample boundary: one upstream HGT
tile is emitted as one 3601x3601 signed 16-bit raster sample. The old recipe
split the same tile into arbitrary row-band samples, which masked the real data
shape.

Usage:

```sh
bash datasets/skadi_srtm_hgt/download.sh
bash datasets/skadi_srtm_hgt/build.sh
bash datasets/skadi_srtm_hgt/verify.sh
```

Default scope:

- tile: `N37W122`
- source: `https://s3.amazonaws.com/elevation-tiles-prod/skadi/N37/N37W122.hgt.gz`
- decoded shape: `3601 x 3601`
- primary values: `12,967,201`
- primary bytes: `25,934,402`
- sample geometry: `2d_raster`

The build does not use the network. It requires only the local downloaded
`N37W122.hgt.gz` under `${DATA_DIR:-.data}/downloads/skadi_srtm_hgt/`.
