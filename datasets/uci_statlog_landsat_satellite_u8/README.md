# UCI Statlog Landsat Satellite Features (uint8)

UCI Statlog Landsat Satellite recipe. The primary payload is native 8-bit multispectral neighborhood values from the train and test tables, emitted row-major without remapping.

Usage:
```sh
bash datasets/uci_statlog_landsat_satellite_u8/download.sh
bash datasets/uci_statlog_landsat_satellite_u8/build.sh
bash datasets/uci_statlog_landsat_satellite_u8/verify.sh
```

Promote to `datasets/` only after the user-run download and local build/verify path succeeds.
