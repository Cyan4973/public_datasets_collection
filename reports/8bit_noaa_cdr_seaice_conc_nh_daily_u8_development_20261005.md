# NOAA/NSIDC sea-ice concentration CDR v4 Northern-Hemisphere daily uint8 development

## Outcome

Accepted `noaa_cdr_seaice_conc_nh_daily_u8`. The family is the native `uint8` `cdr_seaice_conc` raster from every 2022–2024 Northern-Hemisphere daily file of the NOAA/NSIDC Climate Data Record of Passive Microwave Sea Ice Concentration, Version 4 (G02202, `product_version = v04r00`, platform DMSP F17 SSMIS).

Each sample is one UTC day on the 25 km NSIDC polar stereographic north grid: 448 × 304 = 136,192 unsigned bytes, in stored row-major (y, x) order.

The source and the quantity are both new to the corpus. The nearest local family, `noaa_ims_snow_ice_cover_u8`, holds categorical IMS snow/ice classes (0–4) from a different, analyst-driven product. This recipe supersedes the unregistered staging draft `noaa_cdr_sea_ice_concentration_u8`, which depended on netCDF4-python and was never run.

## Source and rights

- Bucket: `s3://noaa-cdr-sea-ice-concentration-pds` (NOAA Open Data Dissemination, us-east-1), read anonymously over HTTPS.
- Scope: `data/final/north/daily/{2022,2023,2024}/seaice_conc_daily_nh_YYYYMMDD_f17_v04r00.nc`, 1,096 files, 258,251,783 bytes.
- Integrity:
  - The file set is pinned by an inventory SHA-256 `3489cfd1292053c64c2a671e3cb93ef0a4fce0a0ded449050a4fda5530760f3d` over (date, key, size, MD5 ETag).
  - Each file is MD5-checked against its `.mnf` checksum manifest and its S3 ETag.
- Rights:
  - The AWS Registry entry `noaa-cdr-oceanic` lists this bucket and states "NOAA data disseminated through NODD are open to the public and can be used as desired", with attribution requested.
  - The bucket's `documentation/UseAgreement_01B-11.pdf` states "the CDR data sets are non-proprietary, publicly available, and no restrictions are placed upon their use".
  - Every file carries `license = "No constraints on data access or use"`, which build and verify check per file.
- Citation: Meier, W. N., F. Fetterer, A. K. Windnagel, and J. S. Stewart. NOAA/NSIDC Climate Data Record of Passive Microwave Sea Ice Concentration, Version 4. NSIDC. https://doi.org/10.7265/efmz-2t65

## Shape and conversion

The natural record is one daily file. The primary sample is that file's `cdr_seaice_conc` variable: dataspace (1, 448, 304), HDF5 unsigned 1-byte little-endian, layout v3 chunked as a single (1, 448, 304) chunk indexed by a v1 B-tree.

Files from 2022-01-01 to 2022-05-31 (151; netcdf 4.7.4 / HDF5 1.10.6, superblock v0) use deflate only. Files from 2022-06-01 to 2024-12-31 (945; netcdf 4.8.1 / HDF5 1.12.2, superblock v2) use shuffle(element size 1) + deflate. A byte shuffle over 1-byte elements is the identity; the recipe asserts this rather than assuming it.

`scripts/h5lite.py` is a narrow pure-stdlib HDF5 reader. It handles v2 object headers with OCHK continuations, and dense links and attributes through the fractal heap and v2 B-trees. It verifies the lookup3 checksum of every metadata block it touches.

The variable is selected by link name, because nine u8 variables share the layout. Build resolves it through the name-index B-tree; verify independently uses the creation-order B-tree and byte-compares every sample.

Stored codes are written unchanged:
- 0–100: percent concentration (`scale_factor` 0.01 gives the area fraction)
- 251 pole_hole, 252 lakes, 253 coastal, 254 land_mask, 255 missing_data

These flags are the variable's own documented `flag_values`, not recipe sentinels.

Excluded: the Southern Hemisphere (a different 316×332 grid), monthly and aggregate files, preliminary/ICDR files, the `ncei_data/` mirror, other years, and all other variables (BT/NT intermediates, stdev, QA, melt onset, interpolation flags).

Provenance spans five NSIDC processing runs in contiguous date blocks, all labelled v04r00: `ade5087`, `c9c632e`, `a11f275`, `22aac63` and `dev`. All produce the identical static mask and code set, and the index records the writer and software version per sample.

## Accepted output

- Primary samples: 1,096 (365 + 365 + 366)
- Values per sample: 136,192 (min = median = max)
- Primary values and bytes: 149,266,432
- Source NetCDF bytes: 258,251,783
- Static mask (identical on all days): 665 lake, 4,561 coastal, 63,707 land cells
- Flag totals: 251: 44; 252: 728,840; 253: 4,998,856; 254: 69,822,872; 255: 18,308
- Concentration cells (1–100) total: 18,165,508. Open-water (0) cells total: 55,532,004.
- Ice cells per day: min 0, median 17,636, max 24,266. Median distinct codes per day: 90.
- Days with missing (255) cells: 3 (2024-09-16: 1; 2024-09-17: 17,453; 2024-09-18: 854). Days with pole-hole cells: 1 (2024-09-17: 44). Days without ice cells: 1 (2024-09-17).
- Writers: 151 netcdf 4.7.4 / HDF5 1.10.6, and 945 netcdf 4.8.1 / HDF5 1.12.2
- Aggregate decoded SHA-256: `7b61c97ea6dc918e7027139de24247a4d2bf0965615bc75f4fdcbc9ffd003b5e`

## Judge checks

- **Gate:** `gate.py` passed with no warnings.
- **Verify:** I ran `verify.sh` myself and it passed in about 10 s. It runs the synthetic self-test, decodes through the creation-order index, byte-compares all 1,096 samples, and recomputes the index and stats. build.sh reads only local `.data/downloads`, and the Python has no network imports. The driver's download log shows `download_check=ok files=1096`.
- **Decode cross-check without h5lite:** a brute-force zlib scan of 24 random source files found 7 candidate 136,192-byte u8 grid streams per file. In every file the emitted sample matches exactly one of them.
- **Semantic cross-check:** I decoded the sibling variables in a superblock-v0 file and a superblock-v2 file. `cdr_seaice_conc` equals max(`nsidc_bt_seaice_conc`, `nsidc_nt_seaice_conc`) in about 65.3–65.8k of about 67.3k ocean cells, which matches the v4 CDR algorithm. No sibling grid is byte-identical to it.
- **Physics:** winter extent is about 21–23.8k cells and September about 6.8–7.6k cells; at 625 km² per cell this matches the known Arctic maximum and minimum. Coarse ASCII maps confirm row-major (y, x) orientation, a frozen Hudson Bay in March and an open one in September, and the fixed land mask.
- **Run homogeneity:** same-month statistics agree across years and processing runs. January mean concentration is 93.9 / 94.0 / 94.0, and March is 93.4 / 94.3 / 94.1. Fraction-of-100% differences across runs are within the interannual spread seen inside a single run.
- **Duplicates:** consecutive days differ in a median of 8,463 cells. The one exact duplicate (2024-09-12 = 2024-09-11) is source-side: its `temporal_interpolation_flag` marks 17,462 cells as filled from the previous day during the September 2024 F17 gap.
- **Rights:** I read the AWS Registry page, which names this bucket and confirms anonymous access with no requester-pays. I fetched the bucket's UseAgreement PDF (MD5 matches its ETag) and extracted the no-restrictions sentence.
- **Novelty:** `novelty.py` on the bucket URL, registry URL, NCEI URL and the sea-ice, G02202, NSIDC, SSMIS and AMSR terms found no accepted recipe, registry row or downstream family. The only hits are the unrelated IMS family and the unregistered draft this supersedes.
- **Caveat:** the material has low entropy. About 51% of every grid is the static mask, and zlib-9 compresses about 10–14× typically. This is native raster content with real daily dynamics, at a bit above the ~100 MB downstream need.
