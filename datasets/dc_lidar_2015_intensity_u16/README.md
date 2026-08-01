# DC LiDAR 2015 Intensity UInt16

This recipe extracts the native two-byte LAS intensity field from three exact
District of Columbia 2015 airborne-LiDAR tiles. One output sample corresponds
to one LAS tile, and point-record order is preserved.

The source tiles are the same pinned files used by the accepted DC LiDAR
classification and GPS-time recipes, but this is a separate numeric family:
laser-return strength rather than a categorical class or acquisition time.
The selected files store intensity as `uint16`, while their realized values
occupy only `0..255`. That narrow-values-in-wide-slots property is retained
exactly rather than repacked to bytes.

The downloader first reuses either accepted DC LiDAR cache and validates every
file by byte size and SHA-256. It contacts the public source only if neither
validated cache is available.

```bash
bash datasets/dc_lidar_2015_intensity_u16/download.sh
bash datasets/dc_lidar_2015_intensity_u16/build.sh
bash datasets/dc_lidar_2015_intensity_u16/verify.sh
```
