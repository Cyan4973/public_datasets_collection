# NOAA OISST Weekly SST Int16 — evaluation-only draft

This recipe is intended exclusively for compression evaluation. It targets the
NOAA Optimum Interpolation Sea Surface Temperature V2 weekly classic-NetCDF
product: 1,727 complete `180×360` grids containing 111,909,600 native packed
signed-int16 values.

Rights remain unresolved for training. The official NCEI metadata requires
citation and refers to a separate CDR Use Agreement whose text was not exposed
by the record. Public availability and free download are not treated as a
training or redistribution license.

Required isolation:

- intended use: evaluation only;
- training eligible: false;
- redistribution authorized: false;
- rights status: unclear;
- all generated material under `.data/evaluation/`; and
- freeze model weights, codec logic, and hyperparameters before evaluation.

Acquire the exact live object qualified during bounded discovery:

```bash
bash evaluation/noaa_oisst_weekly_sst_i16_eval/download.sh
```

The downloader preserves the exact NCEI V2 metadata page, pins the discovered
source size/ETag/last-modified identity, resumes partial downloads, and records
the completed source SHA-256. It does not place anything in the training data
trees.

After acquisition, the recipe will be completed with a dependency-free
classic-NetCDF decoder that emits one complete weekly SST grid per evaluation
sample, byte-swapping XDR big-endian `NC_SHORT` words to canonical
little-endian int16 without applying the `0.01` scale factor.

Build and verify:

```bash
bash evaluation/noaa_oisst_weekly_sst_i16_eval/build.sh
bash evaluation/noaa_oisst_weekly_sst_i16_eval/verify.sh
```

The realized suite spans 1989-12-31 through 2023-01-29 at exact seven-day
intervals. All 1,727 grids are nonconstant and byte-distinct. Stored values
range from -180 to 3616; the declared `32767` missing sentinel does not occur.
