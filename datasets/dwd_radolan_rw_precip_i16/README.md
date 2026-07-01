# DWD RADOLAN RW Precipitation UInt16

This recipe collects recent DWD RADOLAN RW radar precipitation composites and emits one raw little-endian `uint16` sample per composite.

The source material is operational binary radar-rainfall raster data from the German Weather Service open data portal. The natural sample boundary is one RADOLAN composite file. The recipe does not concatenate composites.

Default scope:

- Downloads the newest `${FILE_LIMIT:-192}` timestamped `.bz2` RW files visible in the DWD RADOLAN RW directory.
- Each accepted composite must decode to a `900 x 900` two-byte raster payload.
- Expected raw sample size is `1,620,000` bytes per composite.

Run:

```bash
datasets/dwd_radolan_rw_precip_i16/download.sh
datasets/dwd_radolan_rw_precip_i16/build.sh
datasets/dwd_radolan_rw_precip_i16/verify.sh
```

No dataset payload is committed. All local files are written under `${DATA_DIR:-.data}`.
