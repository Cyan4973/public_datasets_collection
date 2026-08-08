# NASA PDS MOLA MEGDR Int16

This candidate targets signed 16-bit Mars Orbiter Laser Altimeter Mission
Experiment Gridded Data Records from the official NASA Planetary Data System
Geosciences archive.

Run:

```bash
bash datasets/nasa_pds_mola_megdr_i16/discover.sh
bash datasets/nasa_pds_mola_megdr_i16/download.sh
bash datasets/nasa_pds_mola_megdr_i16/build.sh
bash datasets/nasa_pds_mola_megdr_i16/verify.sh
```

The bounded preflight starts from the exact PDS dataset/volume hierarchy,
traverses at most 100 directory listings, and reads at most 200 small PDS3
labels. It accepts only image objects that declare signed 16-bit samples,
nonzero two-dimensional geometry, no line prefix/suffix bytes, and a detached
payload whose remote size exactly matches `LINES × LINE_SAMPLES × 2`.

Discovery downloads no IMG payload. Its results are written beneath
`.data/discovery/nasa_pds_mola_megdr_i16/`.

The bounded collection selects the four complete 64-pixels/degree topography
quadrants (`MEGT*GB`). Each source IMG is a `5760 x 11520` big-endian signed
int16 raster of 132,710,400 bytes. The build byte-swaps each complete natural
quadrant to little-endian int16 without resampling, splitting, or combining
products. Expected primary output is four samples and 530,841,600 bytes.

NASA PDS mission data are public scientific data. Preserve the Mars Global
Surveyor MOLA/PDS attribution in any redistribution or derived collection.
