# NOAA CDR Daily OISST v2.1 — global sea-surface temperature grids (int16)

One primary series, `oisst_v21_sst_daily_i16`. Each sample is the native
`int16` `sst` variable from one final daily file of the NOAA 1/4° Daily
Optimum Interpolation Sea Surface Temperature analysis, Version 2.1
(AVHRR-only, NCEI Climate Data Record, `product_version = "Version v02r01"`).
A sample is one UTC day on the regular global 0.25° grid: 720 latitude rows ×
1440 longitude columns = 1,036,800 values (2,073,600 bytes). Values are in
stored row-major order: latitude from −89.875 northward, longitude from
0.125°E eastward.

| | |
|---|---|
| Scope | the 1st and 15th of every month, 2020-01-01 .. 2024-12-15 |
| Samples | 120 |
| Values per sample | 1,036,800 |
| Primary bytes | 248,832,000 |
| Download | 188,685,403 bytes (120 NetCDF4 files of 1.55–1.70 MB) |

## Source and license

- Bucket: `s3://noaa-cdr-sea-surface-temp-optimum-interpolation-pds` (NOAA
  Open Data Dissemination, us-east-1), read anonymously over HTTPS.
- AWS Registry of Open Data, `noaa-cdr-oceanic`, which lists this bucket:
  "NOAA data disseminated through NODD are open to the public and can be used
  as desired ... NOAA requests attribution for the use or dissemination of
  unaltered NOAA data."
- `documentation/UseAgreement_01B-09.pdf` in the same bucket: "the CDR data
  sets are non-proprietary, publicly available, and no restrictions are placed
  upon their use". It asks for acknowledgement and citation.
- Citation: Huang, B., C. Liu, V. Banzon, E. Freeman, G. Graham, B. Hankins,
  T. Smith, H.-M. Zhang (2020): NOAA 0.25-degree Daily Optimum Interpolation
  Sea Surface Temperature (OISST), Version 2.1. NOAA NCEI.
  https://doi.org/10.25921/RE9P-PT57. Algorithm: Reynolds et al. (2007),
  J. Climate 20, 5473–5496.

Unlike the sea-ice CDR, the OISST files carry no `license` global attribute,
so the license evidence is the registry entry plus the bucket's use agreement.

## Values

`sst` holds integer hundredths of a degree Celsius (`scale_factor` 0.01,
`add_offset` 0, `valid_min` −300, `valid_max` 4500). Observed ocean values run
from −180 (−1.80 °C, the analysis value under sea ice) to about 3,250. In the
probe files the most common ocean value is −180, at 1.5–2.5% of cells.

Land cells hold the variable's `_FillValue` −999. The land mask is static:
345,650 of 1,036,800 cells (33.3%), identical in the 2015, 2020 and 2024
probe files. Build and verify require exactly this count and an identical mask
in every file. Fill is kept as stored, not masked or remapped. The first ~240
latitude rows (Antarctica) are entirely fill, so a byte-prefix of a sample
looks fill-dominated even though the whole grid is two-thirds ocean.

The other variables in the file (`anom`, `err`, `ice`, coordinates) are
excluded. `anom` and `err` are derived from the same analysis, and `ice` is a
separate quantity on a different scale.

## Decode path (pure standard library)

`scripts/h5lite.py` is copied unchanged from the accepted recipe
`noaa_cdr_seaice_conc_nh_daily_u8`, with only a provenance note added. It is a
narrow HDF5 reader that checks the Jenkins lookup3 checksum of every metadata
block it touches.
`scripts/oisst_sst.py`:

1. Opens superblock v2. The probe files from 2015, 2020 and 2024 all use v2,
   though the writer changed: older files carry no `_NCProperties`, while the
   2024 file says `netcdf=4.8.1,hdf5=1.12.1`.
2. Resolves the root link `sst` by **name**. Build uses the name-index v2
   B-tree. Verify uses the creation-order v2 B-tree.
3. Requires:
   - Dataspace `(1, 1, 720, 1440)`
   - Datatype signed 2-byte little-endian
   - Filters exactly shuffle(element size 2) then deflate
   - Layout v3 chunked `(1, 1, 720, 1440, 2)`
   - A v1 chunk B-tree with exactly one leaf entry (offsets 0, filter mask 0)
4. Inflates the chunk to exactly 2,073,600 bytes and undoes the HDF5 shuffle,
   in which byte *j* of element *i* is stored at *j*·n + *i*. Build uses
   strided slice assignment. Verify uses an independent pairwise interleave,
   then byte-compares the result with the sample on disk.
5. Checks variable attributes (`scale_factor` float32 0.01, `add_offset`,
   `_FillValue`, `valid_min/max`, `units`, `long_name`). Also checks global
   attributes: the title must end in "Version 2.1 - Final" and `history` must
   start with "Final file". `product_version`, `processing_level`, the DOI, the
   geospatial bounds and resolution, `id` (must equal the file name) and
   `time_coverage_start/end` (must equal the file date) are checked too. The
   lat/lon `grids` attributes fix the orientation.

`scripts/selftest_oisst.py` runs before build and verify. It builds synthetic
NetCDF4-like files from scratch (superblock v0 and v2, OCHK continuation,
indirect fractal heap, depth-1 name B-tree, creation-order B-tree, dense
attributes, decoy dataset) and checks two things:

- Both decode routes return the exact int16 grid.
- Rejection of a wrong date, a non-final title, shuffle element size 1,
  deflate without shuffle, an extra filter, unsigned or big-endian datatypes,
  a wrong scale factor, a truncated chunk, a missing link, a changed land
  mask, out-of-range values, constant or all-fill grids, and corrupted
  metadata blocks.

## Scope and homogeneity

- One product and version (OISST v2.1 AVHRR-only, final), one grid, one
  variable, one unit and scale (0.01 °C int16), one fill convention and one
  static land mask.
- Dates: the 1st and 15th of each month, 2020–2024. This gives 24 seasonal
  phases per year over 5 years, including the 2020–22 La Niña and the 2023–24
  El Niño. The upstream record is daily from 1981-09 (about 16,000 files,
  about 27 GB). This bounded subset keeps the output near 250 MB.
- Final files only. `discover.sh` read all 60 monthly listings and required
  each month to have every calendar day as a final file and no `_preliminary`
  objects. Preliminary files exist only for the most recent weeks, here
  2026-08 to 2026-10.
- Input streams vary slightly over time. In late 2024 the `source` attribute
  gains `NOAA_ACSP`. Writer versions also differ. The analysis product,
  variable and encoding are unchanged.

## Integrity

- `scripts/inventory.tsv` (120 rows: date, key, size, MD5 ETag) is pinned by
  SHA-256 in `scripts/oisst_sst.py`. The S3 ETag equals the MD5 of the content
  for these single-part objects (checked on three probe files).
- Downloads go to `.part` files with `curl --continue-at -` and stall-based
  limits (`--speed-limit 1024 --speed-time 120`), 6 in parallel, with up to 6
  validation passes. Re-runs skip files that are already valid.
- After download, every file is decoded once as a semantic check.

## Run

```bash
bash staging/noaa_cdr_oisst_v21_sst_i16/download.sh   # ~189 MB
bash staging/noaa_cdr_oisst_v21_sst_i16/build.sh
bash staging/noaa_cdr_oisst_v21_sst_i16/verify.sh
```

`discover.sh` only regenerates the inventory, which is already pinned. Its
listing pages go to `/tmp` by default.

Outputs, relative to `${DATA_DIR:-.data}`:

- `samples/noaa_cdr_oisst_v21_sst_i16/oisst_v21_sst_daily_i16/YYYY/oisst_sst_YYYYMMDD.bin`
- `index/noaa_cdr_oisst_v21_sst_i16/samples.jsonl`
- `filtered/noaa_cdr_oisst_v21_sst_i16/ingest_stats.json`
- logs under `logs/noaa_cdr_oisst_v21_sst_i16/`

## Novelty

The corpus has no SST grid at any width. No local recipe, registry row or
ledger entry uses this bucket. The only NOAA CDR recipe,
`noaa_cdr_seaice_conc_nh_daily_u8`, is sea-ice concentration from a different
bucket. The novelty kind is new quantity in the known modality of gridded
geophysical rasters. Breadth risk: the zlsim gate may find it close to other
smooth int16 geo rasters (soil properties, NDVI, elevation). That is decided
on bytes after the build.
