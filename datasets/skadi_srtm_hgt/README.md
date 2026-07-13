# Skadi SRTM HGT

Exact-ID backfill for the external `skadi_srtm_hgt` reference.

One SRTM HGT tile is a single 3601x3601 signed-16-bit raster (~26 MB) — far too
large to be a useful training sample, and one sample is below the family floor.
The recipe therefore splits the tile row-major into full-width row-band strips
(default 54 rows, final strip shorter). This reproduces the downstream
`srtm_skadi_elevation` family **byte-for-byte** (67 strips for `N37W122`).

Usage:

```sh
bash datasets/skadi_srtm_hgt/download.sh
bash datasets/skadi_srtm_hgt/build.sh
bash datasets/skadi_srtm_hgt/verify.sh
```

Default scope:

- tile: `N37W122`
- source: `https://s3.amazonaws.com/elevation-tiles-prod/skadi/N37/N37W122.hgt.gz`
- decoded tile shape: `3601 x 3601` (big-endian int16 → little-endian int16)
- strips: `67` full-width row bands (`54 x 3601`, final `37 x 3601`)
- primary values: `12,967,201`
- primary bytes: `25,934,402`
- sample geometry: `2d_raster`

Tunables (optional):

| Variable | Default | Meaning |
| --- | --- | --- |
| `SKADI_STRIP_ROWS` | `54` | Rows per row-band strip |
| `SKADI_MIN_SAMPLE_COUNT` | `8` | Minimum strips required for the build to succeed |

The build does not use the network. It requires only the local downloaded
`N37W122.hgt.gz` under `${DATA_DIR:-.data}/downloads/skadi_srtm_hgt/`. Constant
and all-void strips are dropped (none occur for `N37W122`).
