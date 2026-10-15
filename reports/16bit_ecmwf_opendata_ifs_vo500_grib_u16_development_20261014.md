# ECMWF IFS HRES open data 500 hPa relative vorticity GRIB2 packed codes uint16 development

## Outcome

Accepted `ecmwf_opendata_ifs_vo500_grib_u16`. It contains the stored GRIB2 simple-packing 16-bit integer codes of the global 500 hPa relative-vorticity field at the 24 h step. There is one complete field for every 00z ECMWF IFS HRES run published in the open-data `0p4-beta` stream from 2023-01-18 to 2023-06-27.

This is the first family in the local or downstream corpus taken from ECMWF's operational forecast dissemination, and the first in its native GRIB2 packed representation. The nearest related material is the WeatherBench2 ERA5 reanalysis pressure-level float32 fields. Those are a different product (reanalysis, not operational forecast), a different representation (regridded float32), a different archive, and they contain no vorticity. Novelty kind: `new_source`. Gridded atmospheric model fields already exist at 32/64 bits.

## Source and rights

- Source: ECMWF real-time forecasts (open data), AWS Open Data bucket `s3://ecmwf-forecasts` (eu-central-1). The recipe fetches through the registry-listed CloudFront distribution `d2zvc0wgha4k2l.cloudfront.net` and falls back to the S3 endpoint; both serve the same objects.
- Object layout: `<yyyymmdd>/00z/0p4-beta/oper/<yyyymmdd>000000-24h-oper-fc.{index,grib2}`. The recipe takes the single `param=vo, levelist=500, step=24` line of each JSON-lines `.index`, then range-GETs exactly `[_offset, _offset+_length)`, always 811,996 bytes.
- License: CC-BY-4.0 plus the ECMWF Terms of Use. The AWS Open Data Registry entry `datasets/ecmwf-forecasts.yaml` says: "This ECMWF data is published under a Creative Commons Attribution 4.0 International license (CC-BY-4.0) and the ECMWF Terms of Use". The same entry lists the bucket ARN and the CloudFront host. Citation: https://doi.org/10.21957/open-data.
- Access is anonymous HTTPS with no credentials. The data is numerical weather prediction output with no personal data.

## Shape and conversion

- Natural record: one GRIB2 message, which is one complete global field of one 00z run. It holds 900 × 451 = 405,900 points on the 0.4° regular lat/lon grid, in scanning mode 0 (rows from 90 N to 90 S, columns eastward from 180°).
- Download, build and verify all assert the pinned layout for every message:
  - edition 2, centre 98, discipline 0;
  - grid template 3.0 at 900×451 with 0.4° increments and corners (90, 180, -90, 179.6);
  - product template 4.0, parameter 2/12, 24 h step, isobaric 50000 Pa;
  - data template 5.0 with 16 bits and 405,900 points;
  - bitmap indicator 255;
  - total length 811,996 bytes.
- Conversion: section 7 (405,900 big-endian uint16 codes) is byte-swapped to little-endian and written as `<yyyymmdd>.bin` (811,800 bytes). Nothing is requantized. Physical value = `(R + X·2^E)/10^D`. R, E and D for each message are auxiliary metadata in `index/<id>/samples.jsonl` and `filtered/<id>/packing_params.tsv`.
- Window: the bucket starts on 2023-01-18. IFS cycle 48r1 took over on 2023-06-27 at 06 UTC, and from then on the open-data vo/500 messages use CCSDS packing (template 5.42), which has no pure-stdlib decoder. The 2023-06-27 00z run is therefore the last one. Every sample is from cycle 47r3 with template 5.0.
- Source gap: 2023-04-27 to 2023-05-02 (6 days) have no `.index` (HTTP 404), and the S3 listings for those date prefixes are empty. The days are logged in `missing_days.tsv`, and verify requires every day of the window to be either present or logged.

## Accepted output

| Item | Value |
|---|---|
| Calendar days in window | 161 |
| Samples (present runs) | 155 |
| Missing in source | 6 (20230427..20230502) |
| Values per sample | 405,900 (451 × 900) |
| Primary values | 62,914,500 |
| Primary bytes | 125,829,000 |
| Median sample | 405,900 values |
| Download on disk | 128,699,488 bytes (155 messages × 811,996 + 155 index files) |
| Binary scale E | -25 (129), -24 (23), -26 (3); D = 0 throughout |
| code_min / code_max | 0 / 33,159..65,256 |
| Distinct codes per field | 8,294..26,917 (median 15,256) |
| Max single-code share | 0.29% |
| Physical field extremes | min -1.99e-3..-4.26e-4 s⁻¹, max 4.78e-4..2.30e-3 s⁻¹ |
| zlsim breadth | OK; nearest downstream:material_displacement_u16, distance 0.0611, loss 0.0344 |

## Judge checks

- **Mechanics:** I ran `gate.py` myself: PASS with no warnings (62,914,500 values, 125,829,000 bytes, 155 samples, widths [16]).
- **Reproducibility:** I ran `verify.sh` myself and it passed in about 10 s. Its independent section walker re-derived all 155 samples, re-checked hashes, R/E/D and the code statistics, accounted for every window day, and matched the manifest totals. I read `build.sh` and `grib2_vo500.py build`: they use only local `.data/downloads` files and check each message's SHA-256.
- **Bytes:**
  - My own struct decode of the 20230301 (E=-25) and 20230525 (E=-24) messages matches the samples byte-for-byte, and R equals the field minimum.
  - Across 7 decoded samples, reconstructed vorticity has median about 0, p1/p99 about ±1.4e-4 s⁻¹ and p0.1/p99.9 about ±3e-4 s⁻¹, which is plausible for 500 hPa ζ.
  - Every value is ≥256, so the upper byte is always used and the width is not hollow.
  - The pole rows are constant, as expected for a single point.
  - Point-wise correlation between consecutive days is only about 0.1, so there are no near-duplicates. No fill value dominates.
- **Homogeneity:** E varies because ECMWF's encoder fits each field's extremes: E=-24 on days with intense cyclones, E=-26 on calm days. Code-space IQR is about 880, 1700 and 3400 for the three E values. Within E=-25 alone, code_max already spans 35k–60k, so this is the same generation process and representation, not a regime mix.
- **Window evidence:**
  - S3 `list-type=2` returns KeyCount 0 for the `20230428/` and `20230501/` prefixes, but entries for `20230426/` and `20230503/`.
  - The 20230628 00z vo/500 index line has `_length` 546,525, and a CloudFront range probe of that message shows section 5 template 42 at 16 bits. This confirms that the window end is forced by the CCSDS switch and is not a selection choice.
- **Rights:** I fetched the registry YAML myself. The CC-BY-4.0 statement covers "This ECMWF data" in the listed bucket and CloudFront host. No credentials appear in any script.
- **Novelty:** `novelty.py --url` for the bucket, the CloudFront host, data.ecmwf.int and "ecmwf" found nothing. `--terms` found only WeatherBench2 ERA5 f32 downstream rows (no vorticity, not packed). `--type sim_atmos_field` has 4 members, all f32/f64, and the instrument line and archive have 0 members. Precedent for native packed codes: the accepted `mpc_goes18_abi_cmi_c13_fulldisk_u16`.
- **Volume:** the recipe takes the full simple-packed 47r3 00z population (155 runs, 125.8 MB). Range GETs keep the extraction ratio at about 98%.
- **Notes for future recipes:** sibling parameters and levels in the same run files (d500, vo at other levels, tp) must not be proposed as separate families. Data after 48r1 (template 5.42) would need a CCSDS/libaec decoder (`needs_tooling` in pure stdlib).
