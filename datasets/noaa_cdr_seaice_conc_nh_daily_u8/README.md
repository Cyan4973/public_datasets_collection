# NOAA/NSIDC Sea-Ice Concentration CDR v4 — Northern-Hemisphere daily grids (uint8)

One primary series, `cdr_seaice_conc_nh_daily_u8`: the native `uint8`
`cdr_seaice_conc` raster of every 2022–2024 Northern-Hemisphere daily file of
the NOAA/NSIDC Climate Data Record of Passive Microwave Sea Ice Concentration,
Version 4 (G02202, `product_version = v04r00`, platform DMSP F17 SSMIS). Each
sample is one UTC day on the 25 km NSIDC polar stereographic north grid:
448 rows (y) × 304 columns (x) = 136,192 unsigned bytes, in stored row-major
order.

| | |
|---|---|
| Samples | 1,096 (365 + 365 + 366 days) |
| Values per sample | 136,192 |
| Primary bytes | 149,266,432 |
| Download | ≈ 259 MB (1,096 NetCDF4 files of 131–267 KB, 1,096 `.mnf` manifests, 6 listing pages) |

## Source and license

- Bucket: `s3://noaa-cdr-sea-ice-concentration-pds` (NOAA Open Data
  Dissemination, us-east-1), read anonymously over HTTPS.
- Registry of Open Data on AWS, `noaa-cdr-oceanic`: "NOAA data disseminated
  through NODD are open to the public and can be used as desired ... NOAA
  requests attribution".
- `documentation/UseAgreement_01B-11.pdf` in the same bucket: "the CDR data
  sets are non-proprietary, publicly available, and no restrictions are placed
  upon their use", with a request to acknowledge and cite.
- Every file has the global attribute `license = "No constraints on data access
  or use"`. Build and verify check it on every file.
- Citation: Meier, W. N., F. Fetterer, A. K. Windnagel, and J. S. Stewart.
  NOAA/NSIDC Climate Data Record of Passive Microwave Sea Ice Concentration,
  Version 4. NSIDC. https://doi.org/10.7265/efmz-2t65

## Values

`cdr_seaice_conc` holds integer percent concentration 0–100. Multiplying by
`scale_factor = 0.01` gives the area fraction. Five flag codes sit in the same
raster: 251 pole_hole, 252 lakes, 253 coastal, 254 land_mask and 255
missing_data (255 is also the `_FillValue`). These are the variable's own
documented codes, not sentinels added by the recipe. They are kept unchanged,
the way the IMS family keeps its category codes. Lake, coast and land cells form
a fixed mask (665 / 4,561 / 63,707 cells). Verify requires this mask to be
identical on every day.

Some days are degraded in the source. On 2024-09-17, for example, the whole
central-Arctic pack is marked 255 and no cell has 1–100. These days are part of
the official record and are kept as they are. `ingest_stats.json` counts days
with missing cells, days with pole-hole cells and days without any ice cells.

## Decode path (pure standard library)

The files are NetCDF4/HDF5. `scripts/h5lite.py` is a narrow HDF5 reader:

1. Superblock v0 (151 files, 2022-01-01..2022-05-31: netcdf 4.7.4 / HDF5
   1.10.6) or v2 (945 files, 2022-06-01..2024-12-31: netcdf 4.8.1 / HDF5
   1.12.2). The v2 superblock has a checksum, and the reader
   checks it.
2. The root group uses v2 object headers with dense link storage. The reader
   follows Link Info to the fractal heap (a root indirect block of checksummed
   direct blocks), then the v2 B-tree, then the Link messages. Nine `uint8`
   variables share an identical layout, so `cdr_seaice_conc` is selected by
   link **name**, never by position. Build uses the name-index B-tree. Verify
   uses the creation-order B-tree, which is an independent route to the same
   object header.
3. In the variable's header, the reader requires:
   - Dataspace `(1, 448, 304)`
   - Datatype unsigned 1-byte little-endian
   - Filter pipeline of deflate only (v0 files) or shuffle(element size 1) +
     deflate (v2 files). A byte shuffle over 1-byte elements is the identity
     permutation.
   - Layout v3 chunked with chunk dims `(1, 448, 304, 1)`
4. The v1 chunk B-tree must have exactly one leaf entry, with offsets
   `(0,0,0,0)` and filter mask 0. The upper key must be `(1,448,304,1)`. The
   chunk is zlib-inflated and must end exactly at 136,192 values.
5. The reader checks the variable attributes against fixed values:
   `flag_values`, `flag_meanings`, `valid_range` 0..100, float32
   `scale_factor` 0.01, `_FillValue`, `_Unsigned`, `units`, `standard_name` and
   `long_name`. It also checks these global attributes: `cdr_variable`,
   `product_version`, `platform` (F17), `sensor`, `license`, and
   `time_coverage_start`, which must equal the date in the filename.

The reader checks the Jenkins lookup3 checksum of every metadata block it
touches: superblock v2, OHDR/OCHK, FRHP, FHIB, FHDB, BTHD, BTIN and BTLF.
`scripts/selftest_h5.py` runs before build and verify. It builds synthetic
NetCDF4-like files from scratch and checks two things:

- Exact decodes through both link indexes, with superblock v0 and v2. The files
  include an OCHK continuation, an indirect fractal heap, a depth-1 v2 B-tree,
  dense attributes, a global-heap vlen string, and a decoy dataset with the
  same layout.
- Rejection of corrupted blocks, a wrong date, the wrong shuffle element size,
  an extra filter, a signed datatype, a truncated chunk, a missing link,
  undocumented codes and constant grids.

## Scope and homogeneity

- Included: every `data/final/north/daily/{2022,2023,2024}/seaice_conc_daily_nh_YYYYMMDD_f17_v04r00.nc`.
  The listing check fails if any other file name appears under those prefixes.
- Excluded: the Southern Hemisphere (a different 316×332 grid), monthly and
  aggregate files, `data/preliminary/` (ICDR), the `ncei_data/` mirror, other
  years, and every other variable (`nsidc_bt`/`nsidc_nt` intermediate
  estimates, `stdev`, `qa`, melt onset, interpolation flags).
- One hemisphere and grid, one variable, one product version, one sensor
  (F17), and one code set. The CDR was extended in five NSIDC processing
  runs, each covering a contiguous block of dates. All five are labelled
  `v04r00` and produce the identical static lake/coast/land mask:
  - software `ade5087`, 2022-01-01..2022-05-31, 151 days (netcdf 4.7.4)
  - software `c9c632e`, 2022-06-01..2023-09-30, 487 days (netcdf 4.8.1 from here on)
  - software `a11f275`, 2023-10-01..2024-03-31, 183 days
  - software `22aac63`, 2024-04-01..2024-06-30, 91 days
  - software `dev`, 2024-07-01..2024-12-31, 184 days

  The index records the writer and software version per sample. Only three
  days carry missing (255) cells: 2024-09-16 (1 cell), 2024-09-17 (17,453
  cells, no ice cells) and 2024-09-18 (854 cells). Only 2024-09-17 has
  pole-hole (251) cells (44).

## Integrity

- `download.sh` builds `inventory.tsv` from the six listing pages: date, key,
  size and MD5 ETag. It checks that every calendar day is present exactly once
  and that each file has a matching `.mnf`. The inventory text must hash to the
  pinned SHA-256 `3489cfd1…0760f3d`.
- Each `.mnf` (`filename,md5,size`) must agree with the listing. Each NetCDF
  file must match both its size and its MD5.
- Downloads go through `.part` files with `curl --continue-at -` and
  stall-based limits (`--speed-limit/--speed-time`), several files in parallel.
  Files are re-validated between passes, and re-runs skip valid files.
- At the end of the download, every file is decoded once as a semantic check.

## Run

```bash
bash staging/noaa_cdr_seaice_conc_nh_daily_u8/download.sh   # ~259 MB
bash staging/noaa_cdr_seaice_conc_nh_daily_u8/build.sh
bash staging/noaa_cdr_seaice_conc_nh_daily_u8/verify.sh
```

Outputs, relative to `${DATA_DIR:-.data}`:

- `samples/noaa_cdr_seaice_conc_nh_daily_u8/cdr_seaice_conc_nh_daily_u8/YYYY/seaice_conc_nh_YYYYMMDD.bin`
- `index/noaa_cdr_seaice_conc_nh_daily_u8/samples.jsonl`
- `filtered/noaa_cdr_seaice_conc_nh_daily_u8/ingest_stats.json`
- logs under `logs/noaa_cdr_seaice_conc_nh_daily_u8/`

## Novelty

The source is new to the corpus. No accepted recipe, registry row or
downstream family uses this bucket or G02202. The nearest local family,
`noaa_ims_snow_ice_cover_u8`, holds categorical IMS snow/ice classes 0–4 on a
4 km grid. This recipe holds a passive-microwave percent concentration, a
different quantity. It replaces the unregistered staging draft
`noaa_cdr_sea_ice_concentration_u8`, which depended on netCDF4-python and was
never run.
