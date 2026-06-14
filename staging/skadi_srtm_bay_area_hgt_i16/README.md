# Skadi SRTM N37W122 HGT Int16

This staging recipe registers and repairs the locally existing Skadi/SRTM N37W122 elevation material:

```text
/home/cyan/dev/openzl/training_data/numeric_datasets/16bit/datasets/srtm_skadi_elevation
```

That existing material is one HGT tile split into row-band files. The natural sample boundary is the HGT tile, not the row band, so `build.sh` reconstructs a single whole-tile raw little-endian signed 16-bit sample under `${DATA_DIR:-.data}`.

The recipe does not download additional Skadi tiles. `download.sh` only imports already-local row shards, or an explicitly supplied local HGT gzip file.

Expected validated scale:

- Natural samples: 1 HGT tile (`N37W122`).
- Values: `3601 * 3601 = 12,967,201` signed 16-bit elevation values.
- Primary output: `25,934,402` bytes, about `24.7 MiB`.
- Required tools: Python standard library only.

Run with the default local row-shard source:

```bash
staging/skadi_srtm_bay_area_hgt_i16/download.sh
staging/skadi_srtm_bay_area_hgt_i16/build.sh
staging/skadi_srtm_bay_area_hgt_i16/verify.sh
```

Or provide an explicit local source:

```bash
LOCAL_ROWS_DIR=/path/to/srtm_skadi_elevation staging/skadi_srtm_bay_area_hgt_i16/download.sh
```

No dataset payload is committed. All imported and generated files are written under `${DATA_DIR:-.data}`.
