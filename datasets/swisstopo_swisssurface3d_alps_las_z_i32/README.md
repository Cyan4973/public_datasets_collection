# swisstopo swissSURFACE3D 2021 High-Alpine Lidar: LAS Int32 Z

This recipe collects the native LAS int32 Z field from 15 complete 1 km2 tiles
of swisstopo's swissSURFACE3D classified airborne-lidar point cloud (2021
acquisition, Bernese Oberland / Aletsch region, LV95/LN02). One sample is one
tile: the Z code of every point record (all returns, all classes) in file
order, written as raw little-endian int32. Height = Z * 0.01 m, offset 0, so
the codes run from about 161,000 to 388,000 and use about 19 bits.

Source: data.geo.admin.ch STAC collection `ch.swisstopo.swisssurface3d`.
License: swisstopo OGD ("Opendata BY: Open use. Must provide the source.").
Attribution: **©swisstopo**.

## Selection and homogeneity

`scripts/discover.py` documents the rule and checks that it still produces
`sources.tsv`:

1. STAC items in bbox `7.85,46.40,8.15,46.60`: 647 items in total (2021: 398,
   2022: 224, 2023: 25).
2. Keep 2021 tiles that have no item from another year (drops the partial
   tiles on acquisition-block borders): 327.
3. Keep tiles with the uniform delivery profile: LAS 1.2, point format 1,
   28-byte records, no VLRs, scale 0.01, Z offset 0, LAStools `las2las`. This
   drops two `lasmerge` tiles, leaving 325.
4. Sort by id and take 15 evenly spaced tiles (index `floor(j*325/15 +
   325/30)`).

All tiles are high-alpine: the per-tile Z range is 1,612-3,883 m, and each
tile has 12.8-22.0 M points. The sample count is limited by the natural 1 km2
tile boundary and the 1 GB primary cap: 15 tiles give 955,570,404 bytes.
Tiles are not sharded.

## Running

```bash
bash staging/swisstopo_swisssurface3d_alps_las_z_i32/download.sh   # ~2.76 GB of zips
bash staging/swisstopo_swisssurface3d_alps_las_z_i32/build.sh
bash staging/swisstopo_swisssurface3d_alps_las_z_i32/verify.sh
```

`download.sh` checks the pinned zip size and the STAC SHA-256. It also
requires a single member with the pinned size and CRC-32, and the expected LAS
header profile, then fully inflates the member. `build.sh` streams the member
without extracting it, and requires the data Z min/max to equal the header
bounds. `verify.sh` re-derives every sample by a separate decoding path and
compares bytes.
