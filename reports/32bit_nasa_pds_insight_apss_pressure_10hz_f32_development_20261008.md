# InSight APSS 10 Hz Mars surface-pressure float32 development

## Outcome

Accepted `nasa_pds_insight_apss_pressure_10hz_f32`. The recipe collects calibrated Mars surface atmospheric pressure, sampled at 10 Hz by the InSight lander's APSS pressure sensor. Each sample is one full-sol PDS4 product.

This is the corpus's first planetary-meteorology family. Barometric pressure appears locally only as Earth station or reanalysis series: `noaa_coops_air_pressure` (f64, hourly) and the NASA POWER surface state (f64, daily). Downstream it appears only as `open_meteo_surface_pressure_f32` (hourly reanalysis) and `ndbc_pres` (f64). None of these carries a high-rate in-situ turbulence and vortex signal. Novelty kind: `new_source`. The measured zlsim verdict is OK: the nearest family is `zenodo_spica_urban_das_f32` at distance 0.0692.

## Source and rights

- Source: NASA PDS Atmospheres Node, bundle `urn:nasa:pds:insight_ps`, collection `data_calibrated` (<https://atmos.nmsu.edu/PDS/data/PDS4/InSight/ps_bundle/data_calibrated/>), anonymous HTTPS.
- Pinned files: 28 `ps_calib_<SOL>_<VV>.csv` products, product versions 1.0/2.0, files dated 2023. `files.tsv` pins the byte size, the PDS4-label MD5 and the table record count for each file.
- Downloaded bytes: 2,540,943,006.
- License: CC0-1.0 under the NASA science data license (<https://science.data.nasa.gov/about/license>). Unless a file is marked with a restrictive notice, observational, engineering, calibration and auxiliary data from a NASA-led mission "are licensed as Creative Commons Zero". InSight is a JPL-led NASA Discovery mission, and the APSS pressure sensor was JPL-provided. Neither the product labels nor the bundle label carries any license or restriction element.
- Citation: Banfield, D., APSS PS bundle, PDS Atmospheres Node, DOI 10.17189/1518939 (resolves to `urn:nasa:pds:insight_ps`); Banfield et al. 2019, Space Sci Rev 215:4.

## Shape and conversion

Each natural record is one full-sol calibrated product: a PDS DSV table with 9 fields and CRLF line endings, holding about 887,770 records over about 88,775 s.

**Selection.** All 496 products listed at about 87 MB qualify by their labels: 887,000-888,500 records, a span of 88,700-88,800 s, and the standard schema. The recipe takes 28 at evenly spaced positions of the sol-ordered list. This rule was fixed before looking at any values. Eligible products are concentrated in sols 123-832, with only 8 after sol 832, so the pick jumps from sol 809 to sol 1098.

**Conversion.**
- Field 6 `PRESSURE` (ASCII_Real `%10.4f`, pascal) is parsed to the nearest IEEE float32.
- Values are written little-endian in source row order.
- Every stored value rounds back to the identical 4-decimal source string. The float32 half-ulp below 1024 Pa is 3.05e-5, under the 5e-5 needed.
- Not emitted: the timestamps (AOBT, SCLK, LMST, LTST, UTC), `PRESSURE_FREQUENCY`, and the 0.2 Hz `PRESSURE_TEMP`. There are no auxiliary series.

**Missing-value policy.**
- Rows with an empty PRESSURE are dropped and counted.
- Rows not at 10 Hz are dropped and counted; more than 1% of a file's rows is fatal.
- A malformed decimal, a value outside [100, 1500] Pa, a failed round trip, a wrong field or record count, or a size/MD5 mismatch is fatal.
- In the realized build, 0 blank and 0 non-10 Hz rows were dropped.

## Accepted output

- Primary samples: 28, at sols 169, 189, 208, 228, 255, 304, 327, 346, 365, 399, 419, 445, 463, 481, 504, 522, 540, 559, 590, 608, 650, 669, 689, 712, 748, 770, 809 and 1098.
- Primary values: 24,857,573
- Primary bytes: 99,430,292
- Sample size:
  - minimum 887,702 values (sol 365, which has one 7.1 s gap)
  - median 887,773 values
  - maximum 887,780 values
- Value range: 593.0015-811.9196 Pa. Per-sample means run 619.8-791.0 Pa, following the CO2 seasonal cycle.
- Distinct values per sample: 241,577-374,285.
- Coverage: sols 169-1098, which is 930 sols or about 1.39 Mars years. The manifest's "more than 1.4 Mars years" is a slight overstatement; the realized sol list above is authoritative.

## Judge checks

- **Gate:** `gate.py` PASS, no warnings.
- **Verify:** I re-ran `verify.sh` after the builder's final manifest-note edit. It exited 0 in 63 s; the synthetic selftest passed and all 28 samples re-derived byte-identically through the independent csv-module path. Index min/max are from the stored float32, and ingest stats and manifest totals match.
- **Build is local:** `build.sh` reads only local downloads and contains no network code.
- **Bytes:** I inspected all 28 samples with `struct`.
  - One float32 exponent band (512-1024 Pa), and a uniform last-decimal-digit distribution: a genuine 1e-4 Pa lattice.
  - Median |delta| is 32-133e-4 Pa. Zero second differences are only 0.2-0.7% and identical-value runs are at most 4 long, so there is no interpolation or hold.
  - Per-sol noise profiles show daytime convective peaks and raised nighttime turbulence around sols 590-689 (the windy season): physical variation within one process.
- **Raw cross-check:** I parsed the sol 365 and sol 608 CSVs myself. Stored values equal the PRESSURE column row for row, and AOBT steps are 0.1 s throughout.
- **Rights and pins:** I opened the NASA license page. I fetched the product labels for sols 419 and 1098 (MD5 and records match `files.tsv`) and the bundle label (no restrictive notice). The DOI resolves to the bundle.
- **Selection:** I re-counted the 14 sol directory listings and found exactly 496 full-sol 87M products.
- **Novelty:** `novelty.py` with the URL, distinctive terms, and type/instrument/archive keys. No matching recipe, registry entry or downstream family; 0 entries share the instrument line or archive collection.
- **Volume:** 28 samples (above the ~20 guidance) and about 99 MB primary, which matches the roughly 100 MB downstream budget. The roughly 25:1 extraction ratio is tolerable: the kept signal is large and no binary product exists.
