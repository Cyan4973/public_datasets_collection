# UVA_VPTS German weather-radar animal reflectivity (eta) float32 development

## Outcome

Accepted `aloft_uva_vpts_animal_reflectivity_f32` from the frozen UVA_VPTS Zenodo deposit (record 14711244, published 2025-01-25, latest version of concept DOI 10.5281/zenodo.13629330).

This is the corpus's first radar-aeroecology family. vol2bird estimates the reflectivity of biological scatterers (mostly nocturnally migrating birds) from German Weather Service (DWD) C-band volume scans, for 25 altitude bins of 200 m (0–4800 m). It differs from the accepted DWD RADOLAN precipitation raster (`dwd_radolan_rw_precip_i16`) and from the 8-bit weather-radar rasters (FMI PPI VRAD, NEXRAD NIDS, SEVIR VIL). It has a different product, generation process, quantity and shape: a time-by-height profile series rather than a polar or Cartesian raster.

## Source and rights

| file | bytes | Zenodo MD5 |
| --- | ---: | --- |
| `de.tgz` | 1,231,349,011 | `77459683bb0d30c16af21ab2d706b260` |
| `coverage.csv` | 920,447 | `cdc339b008122fcebc9d3414969c07a4` |
| `vpts-csv-table-schema.json` | 7,238 | `f94e2865bb363c56f37e1b4cd87edba2` |

- License: CC0 1.0. The Zenodo record metadata declares `cc-zero` at record level (open access), which covers every deposit file. The Aloft FAQ states: "The data in the bucket are available under a Creative Commons Zero waiver." The record lists the bucket's `uva/monthly/` prefix as `isVariantFormOf`.
- Only the `uva/` deposit is used (UvA processing of DWD inputs). The Aloft `baltrad/` prefix depends on OPERA research-only raw inputs and is never touched. Belgian (`be.tgz`) and Dutch (`nl.tgz`) archives are not downloaded.
- `download.sh` checks record id, title, publication date, license and all three size/MD5 pins through the Zenodo API. It then streams the archive and requires its members to equal coverage.csv's 465 German radar-months.

## Shape and conversion

- **Sample:** one published radar-month VPTS CSV (`de/<radar>/<year>/<radar>_vpts_<YYYYMM>.csv.gz`), emitted as a row-major little-endian float32 matrix of shape (profiles, 25) in stored row order (profile, then height). This is the deposit's documented file unit. A single profile is a 25-value time step of the series, not an independent record.
- **Kept column:** `eta` only (cm^2/km^3).
- **Excluded columns:**
  - `dens`: eta/11 with screened bins zeroed, i.e. a scaled, masked copy of eta.
  - `dbz`: a log transform of eta.
  - `dbz_all`: includes precipitation.
  - Also excluded: the kinematics, the `gap` flag, the `n_*` counts and the radar metadata.
- **Conversion:** each finite decimal is rounded once to IEEE binary32. The schema missing tokens `''`, `NA` and `NaN` become the canonical NaN 0x7fc00000.
- **Precision:**
  - 99.93% of finite tokens recover the vol2bird binary32 bit-exactly: 5,813,770 exact and 18,957,501 unique within one last written place.
  - 17,329 tokens (0.07%), all in 7 fixed-decimal files (deboo/dehnr 2017-11 and 2018-11, deros 2017-11, defld 2018-11, deess 2018-11), were published with fewer digits than float32 resolution. They are stored as the nearest binary32 and counted per sample.
  - The series is labelled `derived_operational_numeric`. The width is the source's native binary32.
- **Enforced per file:** the exact 26-field VPTS CSV header; the 0..4800 m step 200 m grid for every profile; unique in-month datetimes; rcs 11; sd_vvp_threshold 2; C-band wavelengths; a consistent ODIM/WMO radar id; and per-month and per-day row counts equal to coverage.csv.
- **Stored order is kept.** Two files (denhb 2015-04, deumd 2015-09) list one day's hourly profiles before that day's remaining profiles, one order break each, recorded in the index.

## Accepted output

| metric | value |
| --- | --- |
| samples | 465 radar-months from 18 radars, 2015-02 to 2019-05 |
| primary values | 28,369,050 |
| primary bytes | 113,476,200 |
| median / min / max sample | 71,200 / 4,800 / 223,100 values |
| profiles | 1,134,762 (15-min cadence in 461 months, 5-min in 4) |
| NaN | 3,580,450 (12.62%): 3,237,714 `NaN`, 342,736 blank, 0 `NA` |
| zeros | 2,518,712 (10.16% of finite values) |
| finite range | 0 to about 21,117 cm^2/km^3 |
| aggregate SHA-256 of sample SHA-256s | `a763eb29196e357598a8df0ab52676f1089a757e22186349e49f8560eb1f8ada` |

## Judge checks

- **Gate:** `python3 tools/autocollect/gate.py staging/aloft_uva_vpts_animal_reflectivity_f32` gave PASS with no warnings. Primary values 28,369,050, bytes 113,476,200, 465 samples, median 71,200, width 32.
- **Reproducibility:**
  - I ran `verify.sh` myself: verify_ok, with the aggregate SHA-256 above, in 1m46s. Its parser is independent of the build: line splitting and `array('f')`, a byte-compare of all 465 samples, and coverage, index, count and degeneracy checks.
  - `build.sh` reads only local `.data/downloads` files.
  - No credentials appear in any script.
- **Bytes:**
  - I unpacked 8 samples with `struct`. All finite values are non-negative, with exponents 114–140 (full float32 range) and medians falling with height. Bins below the antenna are always NaN, using the single NaN word 0x7fc00000.
  - All 465 sample hashes are unique.
  - My own `csv.DictReader` + `struct.pack('<f')` parse of deess 2018-11, deemd 2016-02 and denhb 2015-04 matched the emitted bytes exactly.
- **Homogeneity:**
  - I scanned the whole archive once. Profiles with R temp-file source names (166,582, in 72 files) and with vol2bird v0.3.20 names (968,180) have matching eta distributions (p50 5.5 vs 3.6, p99 457 vs 394, zero fraction 11.5% vs 9.9%).
  - 1.3% of profiles are identical to the previous profile. In the file I classified they are all-NaN failed scans or all-zero empty scans.
  - The two order breaks are same-version v0.3.20 outputs that the publisher listed out of order.
- **Rights:** I opened the Zenodo record (`license.id = cc-zero`) and the Aloft FAQ (CC0 waiver for the bucket). The OPERA research-only clause applies only to `baltrad/`.
- **Novelty:** `tools/autocollect/novelty.py` with the Zenodo and Aloft S3 URLs and terms aloft/vpts/vol2bird/animal reflectivity/aeroecology/bioRad found no recipe, registry, ledger or downstream hits other than this candidate. Labelled `new_source`, not `new_modality`, because weather radar is already in the corpus.
- **Not verified:** the builder's mention of an 11-case synthetic self-test does not correspond to any file in the recipe. It is not needed for acceptance, because verify.sh re-derives every sample independently.
