# NOAA CDR OISST v2.1 sea-surface temperature int16 development

## Outcome

Accepted `noaa_cdr_oisst_v21_sst_i16`: 120 final daily global sea-surface temperature analyses from the NOAA 1/4° Daily Optimum Interpolation SST v2.1 climate data record (AVHRR-only, `product_version = "Version v02r01"`). Each sample is the native int16 `sst` variable of one daily NetCDF4 file.

This is the first sea-surface temperature grid in the corpus at any width, locally or downstream. It is a new quantity within the already populated `geo_product_raster` modality. The only related recipe, `noaa_cdr_seaice_conc_nh_daily_u8`, is a different CDR (sea-ice concentration) from a different bucket.

## Source and rights

- Source: the anonymous NOAA Open Data Dissemination bucket `noaa-cdr-sea-surface-temp-optimum-interpolation-pds` (us-east-1), keys `data/v2.1/avhrr/YYYYMM/oisst-avhrr-v02r01.YYYYMMDD.nc`.
- Scope: the 1st and 15th of every month, 2020-01-01 to 2024-12-15, final files only. `discover.sh` required every month to be complete and to contain no `_preliminary` objects.
- Pinning: `scripts/inventory.tsv` holds 120 rows of date, key, size and single-part MD5 ETag. The inventory's SHA-256 `6ffd557f3076b29686bd176f3e9b1233c60b8e83af780db72241dfb23e984c75` is pinned in `scripts/oisst_sst.py`. Total source size is 188,685,403 bytes.
- License: the AWS Registry of Open Data entry `noaa-cdr-oceanic` lists this exact bucket under: "NOAA data disseminated through NODD are open to the public and can be used as desired... NOAA requests attribution for the use or dissemination of unaltered NOAA data."
- The bucket's `documentation/UseAgreement_01B-09.pdf` (21,679 bytes, MD5 `51951d39e24c650ceb99027cc533023b`) states: "the CDR data sets are non-proprietary, publicly available, and no restrictions are placed upon their use."
- Citation: Huang et al. (2020), DOI 10.25921/RE9P-PT57, kept in the manifest.

## Shape and conversion

- Natural record: one daily file holds one complete global 720×1440 analysis grid on the regular 0.25° lat/lon grid. Latitude runs from -89.875 northward; longitude runs from 0.125°E eastward.
- Decode: `scripts/h5lite.py`, a pure-stdlib HDF5 reader copied unchanged from the accepted sea-ice recipe that checks the lookup3 checksum of every metadata block it touches. It resolves the root link `sst` by name, then requires:
  - dataspace (1,1,720,1440)
  - signed little-endian 2-byte datatype
  - filters exactly shuffle(2) then deflate
  - one chunk (1,1,720,1440) with offsets 0 and filter mask 0
- The chunk is inflated to exactly 2,073,600 bytes and the 2-byte shuffle is undone. The stored integers are written unchanged, with no scaling, masking or remapping.
- Attribute checks: scale_factor float32 0.01, add_offset 0, _FillValue -999 and valid range -300..4500. The title must end in "Version 2.1 - Final" and history must start with "Final file". The `id` attribute must equal the file name, and the time coverage must equal the file date.
- Missing values: land keeps the native `_FillValue` -999. It is a static mask of 345,650 of 1,036,800 cells (33.3%), and every file carries the same mask (one mask SHA-256). Build and verify both reject any other fill count or mask.
- Excluded: the `anom`, `err` and `ice` variables and the coordinate variables.

## Accepted output

- Primary samples: 120 (24 per year, 2020-2024)
- Values per sample: 1,036,800 (median 1,036,800)
- Primary values: 124,416,000
- Primary bytes: 248,832,000
- Ocean value range: -180 to 3,634 hundredths of °C. The maximum is on 2023-08-15.
- Ocean mean: 1,400.2 (14.0 °C)
- Distinct ocean values per sample: 3,273 to 3,713
- Most common ocean value share per sample: 0.73% to 5.09%. The value is -180, the freezing point under sea ice.
- Writer metadata: 112 files without `_NCProperties`; 8 files with netcdf 4.8.1 / HDF5 1.12.1
- Aggregate decoded SHA-256: `931d6677f3c51aa259938c25ee68eff0a128bbbb8ad58218f5c709441a205366`

## Judge checks

- **Gate:** `gate.py` passed with no warnings.
- **Verify:** I re-ran `verify.sh` and it passed. Verify uses an independent link route (the creation-order B-tree) and a different unshuffle from build. It byte-compares all 120 samples, re-checks the index, the stats and the manifest totals, and finds no stale files.
- **Integrity:** the inventory SHA-256 matches the pin, and the size sum matches the download log (188,685,403 bytes). Build and verify contain no network code or credentials.
- **Independent decode:** I scanned three raw `.nc` files (2020-01-01, 2023-08-15, 2024-12-15) for zlib streams that inflate to 2,073,600 bytes, without using h5lite. Each file holds four such streams:
  - `anom`, about ±1,000
  - `err`, 11..74
  - `ice`, 15..100
  - `sst`

  Exactly one stream matches the sample byte-for-byte, and it has the SST range. The variable order differs between files, and the name-based selection still picks `sst`.
- **Bytes:** I unpacked six samples with `struct`. Band means are physically correct:
  - equator: 27.3-28.2 °C
  - N40-N50: 9.4 °C in January, 14.6 °C in July, 17.3 °C in October
  - Southern Ocean: reversed seasonality (4.8 °C in January, 3.1 °C in June)
  - Arctic: about -0.8 °C in winter

  Consecutive samples share only about 7% identical ocean cells, with a mean change of 0.5-0.6 °C. Year-apart pairs differ by 0.8-0.9 °C. All 120 payload hashes are distinct.
- **Rights:** I fetched the registry YAML and confirmed its License field covers the listed OISST bucket ARN. I fetched the use-agreement PDF, confirmed its MD5 matches the pin, and confirmed the quoted text is verbatim.
- **Novelty:** `novelty.py` URL and term searches (OISST, sea surface temperature, GHRSST, MUR, ERSST, HadISST, sst) found no SST family in recipes, the registry, the ledger or downstream. No family shares the instrument line or archive.
- **Breadth:** the measured verdict is OK. The nearest family is `tcia_lung_pet_ct_dx_u16` (whole-body PET activity) at distance 0.1184 with compression loss 0.0548, above the 3% equivalence bound.
- **Fill:** the fill is the documented native `_FillValue` over a static land mask, at 33.3% of each grid. That is below dominance, and the driver raised no fill warning.
- **Erratum:** the README says "the first ~240 latitude rows (Antarctica) are entirely fill". In fact only rows 0-45 (-89.875° to -78.625°) are entirely fill. Southern rows up to row 74 are majority fill. This is a documentation slip only and does not affect the data.
