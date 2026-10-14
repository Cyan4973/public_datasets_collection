# NOAA NOHRSC SNODAS masked CONUS snow water equivalent (int16)

Staged recipe for daily 1 km (30 arc-second) **snow water equivalent** (SWE)
grids from the NOAA National Weather Service NOHRSC Snow Data Assimilation
System (SNODAS). NOAA@NSIDC archives them as data set G02158
(DOI [10.7265/N5TB14TC](https://doi.org/10.7265/N5TB14TC)).

- Product: SNODAS product code 1034, "Modeled snow water equivalent, total of
  snow layers". Units are `Meters / 1000` (mm), slope 1, intercept 0, raw
  big-endian 2-byte signed integers.
- Grid: masked CONUS, 6935 columns x 3351 rows, WGS84. The benchmark cell
  centre is (-124.729167, 52.870833) and cells are 0.00833333 deg. All
  selected dates fall after the October 2013 masked-grid change. Their headers
  share the same geometry; only timestamps, comment strings, product-code
  counters and bounding-box digits past the 1e-11 place differ.
- Scope: 20 dates, 15 January and 15 February of each year from 2017 to 2026,
  near peak CONUS snow-cover extent. Each date is one natural record (one
  complete daily grid, 23,239,185 values, 46,478,370 bytes). The expected
  primary output is 20 samples and 929,567,400 bytes, under the 1 GB cap.
- Excluded: snow depth, melt, sublimation, precipitation and temperature
  products from the same tars. They are separate quantities and are never
  fetched.

## Download (range GETs, not whole tars)

Each daily tar (`masked/YYYY/MM_Mon/SNODAS_YYYYMMDD.tar`, about 20-30 MB)
holds 8 products as `.dat.gz`/`.txt.gz` pairs. `scripts/discover.py`
resolved the plan with 512-byte header reads and 8-byte trailer reads only.
It walked the ustar headers, located the SWE members, and read each
`.dat.gz` gzip trailer. `plan.tsv` pins the following per date:

- tar URL and member names
- tar offsets and member byte sizes
- gzip CRC32 and ISIZE of the decompressed raster (ISIZE is always
  46,478,370 = 6935x3351x2)

`download.sh` handles each member as follows:

1. It range-fetches the member's 512-byte ustar header. It checks the
   header checksum and that the name and size match the plan.
2. It range-fetches the member and rejects short reads, in case a server
   ignores `Range`.
3. For the `.txt.gz` member, it parses the NOHRSC header and checks:
   description, units `Meters / 1000.000000`, `integer`, 2 bytes/pixel,
   slope 1, intercept 0, no-data `-9999`, 6935 columns, 3351 rows, WGS84,
   resolution, benchmark and bounding box, the data file name, and the start
   date.
4. For the `.dat.gz` member, it fully decompresses the data. It checks that
   the length is 46,478,370 and that both the trailer and the recomputed
   CRC32 equal the pinned value.

NSIDC publishes no per-file MD5 values. The pinned CRC32 plus ISIZE fixes the
decompressed raster content. `download.sh` also writes the md5 and sha256 of
every fetched member to `downloads/<id>/member_checksums.tsv`. The expected
download is about 96.7 MB: 96,725,811 member bytes plus 40 header blocks.

Optional mirror override, with the same directory layout:
`SNODAS_BASE_URL=https://mirror/NOAA/G02158/masked bash download.sh`.

## Build and verify

`build.sh` reads only local files and works as follows:

- It re-checks each `.txt` header and gunzips the raster.
- It byte-swaps the big-endian int16 values to little-endian, in the
  original row-major order (rows north to south, columns west to east).
- It writes `samples/<id>/snodas_swe_mm_i16/snodas_swe_<date>_masked_3351x6935.bin`.
- It writes `index/<id>/samples.jsonl` with per-sample counts of no-data,
  zero and positive cells, the count of `32767` values, the number of
  distinct values, min/max, the sha256 of the no-data mask, and the sample
  sha256.
- It writes `filtered/<id>/ingest_stats.json`. This file includes whether the
  no-data mask is identical across all dates.

`verify.sh` re-derives the output independently:

- It re-gunzips each source member and swaps bytes by slice assignment
  rather than `array.byteswap`. Each sample must match byte for byte.
- It recomputes every index statistic and the mask hash.
- It checks the manifest `sample_count` and `total_size_bytes` against the
  realized output.
- It rejects degenerate grids: under 1% positive cells, under 500 distinct
  values, or 50% or more no-data. Any negative value other than -9999 is
  also rejected.

## Value distribution (known caveat)

- `-9999` marks cells outside the CONUS land mask (ocean, Canada, Mexico).
  It is the native SNODAS mask, covers about 48.4% of every grid, and is
  expected to be the same on every date (the build reports whether it is).
  It is kept as-is, not removed or remapped.
- `0` means no snow. In the realized 20 mid-winter grids it covers
  13.4%-39.2% of the grid (median about 30%). For comparison, the
  2024-03-01 self-test had 41.5%, which is why mid-winter dates were chosen.
- Positive SWE covers 12.4%-38.2% of the grid (2021-02-15 is the
  maximum), with 1,334-2,603 distinct values per grid.
- The build confirmed the no-data mask: it is byte-identical on all 20
  dates (one distinct mask sha256), at 48.41% of cells.
- A handful of cells, mostly glaciers and permanent snowfields, reach
  `32767`, the header's stated maximum and very likely a saturation cap.
  The count per grid is 0 in 2017-2020-01, then rises steadily to 15 in
  2026 (86 cells over all 20 grids, at most 6.5e-7 of a grid). That is
  consistent with perennial accumulation reaching the int16 ceiling. The
  values are kept as-is and the count is recorded for every sample.

## License

SNODAS is a NOAA NWS NOHRSC product, so it is a U.S. Government work
(17 U.S.C. 105). NSIDC states "NOHRSC provides/creates the data, we just
archive it". The NSIDC page names no license but requires citation: "As a
condition of using these data, you must cite the use of this data set."
This is the same host and licence basis as the accepted
`noaa_ims_snow_ice_cover_u8`.

Citation: National Operational Hydrologic Remote Sensing Center. (2004).
Snow Data Assimilation System (SNODAS) Data Products at NSIDC (G02158,
Version 1). Boulder, Colorado USA. NSIDC. https://doi.org/10.7265/N5TB14TC

## Run

```bash
bash staging/nsidc_snodas_masked_swe_i16/download.sh
bash staging/nsidc_snodas_masked_swe_i16/build.sh
bash staging/nsidc_snodas_masked_swe_i16/verify.sh
```
