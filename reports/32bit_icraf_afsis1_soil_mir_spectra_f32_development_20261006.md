# AfSIS Phase I soil MIR absorbance spectra float32 development

## Outcome

Accepted `icraf_afsis1_soil_mir_spectra_f32` from the pinned ICRAF Dataverse deposit doi:10.34725/DVN/QXCWP1, version 1.1, released 2025-06-19.

This is the first laboratory vibrational (FTIR) spectroscopy family in the corpus at any width. Each sample is one soil sample's mid-infrared diffuse-reflectance absorbance spectrum. The only other soil recipe, `isric_soilgrids_clay_i16`, is a mapped clay-content raster, a different quantity and process. Every family accepted at 32-bit in this effort so far is neuro or medical, so this one also adds breadth.

## Source and rights

- Source: ICRAF Dataverse, "Mid-Infrared Spectra (MIRS) from ICRAF Soil and Plant Spectroscopy Laboratory: Africa Soil Information Service (AfSIS) Phase I 2009-2013", V1.1.
- Files: 19 original-format country CSVs (datafile ids 10916-10934), 327,146,877 bytes, each pinned by Dataverse original size and MD5. Datafile 10842, "0. Disclaimer.pdf", is skipped.
- License: CC BY 4.0. The dataset `termsOfUse` reads: "This dataset is made available under the Creative Commons Attribution 4.0 International license (CC-BY-4.0). The license allows you, the user, to copy and redistribute the material in any medium or format and/or transform, and build upon the material for any purpose, even commercially." The `conditions` field asks for credit, a license link and indication of changes. The structured `license` field is `NONE` because the grant sits in these custom terms. No file is restricted and there is no `termsOfAccess`.
- Instrument: the dataset description states that all of the "~18,500 samples" were measured at ICRAF's Soil-Plant Spectral Diagnostics Laboratory in Nairobi on a Bruker Tensor 27/HTS-XT.

## Shape and conversion

Each natural record is one CSV row, keyed by ICRAF sample number (SSN). A sample is that row's 1,749 absorbance values in source column order: descending wavenumber from 4001.6 to 601.7 cm-1 at about 1.93 cm-1 spacing, with the provider's CO2 gap between m2381.7 and m2350.8. All 19 files share one byte-identical 1,753-column header (SHA-256 `570c81aa54a569adea4c11b444c4861758296f283e06f77c95c3e0023b830d11`). The columns Num, SSN, Depth and Country go only into the sample index.

Each decimal cell is rounded once to IEEE-754 binary32 and written little-endian, following the pfam and powder-XRD precedents. Every emitted cell lies on a 2.5e-7 grid, and the printed-digit split matches means of 4 replicate 6-decimal readings: 25.0% have 6 or fewer digits, 25.0% have 7, and 50.0% have 8, all ending in 25 or 75. Because |value| < 4, the grid integer stays below 2^24, so `round(f32 * 4e6)` recovers every source value exactly. Build checks this for every cell with integer parsing and verify with `decimal.Decimal`. Values of 4 or more would be fatal.

Excluded rows (10 of 18,257) are detected by rule and must equal pinned SSN sets:

- 7 placeholder rows whose cells are all `NA`, meaning no spectrum was recorded.
- 3 rows on a k/3e6 grid printed to 9 decimals, i.e. 3-replicate means (Kenya icr033584, Mali icr037556, Zambia icr075955).

Partial NA, off-grid values, wrong column counts, duplicate SSNs and unknown Depth or Country values are all fatal. Nothing is imputed.

## Accepted output

- Source rows read: 18,257 across 19 countries
- Primary samples: 18,247 (9,466 topsoil, 8,781 subsoil); per country from 304 (Burkina Faso) to 2,080 (Tanzania)
- Primary values: 31,914,003
- Primary bytes: 127,656,012, 6,996 per sample
- Stored range: 0.077458 to 3.047060 absorbance
- Worst float32 error: 0.476807 grid steps, below the 0.47684 bound
- Distinct values per sample: at least 1,743
- Duplicate spectra: none
- Aggregate payload SHA-256: `3481c4a2e37c05c59a4f6593574c3662b6a40782dd60b138d6a7d7e1d6aad2ab`

## Judge checks

- **Gate:** `gate.py` passed with no warnings (values 31,914,003, bytes 127,656,012, samples 18,247, median 1,749 values, width 32).
- **Verify:** I reran `verify.sh`: exit 0, `verify_ok`, matching aggregate SHA-256.
- **Self-test:** `afsis_mir.py selftest` passed: 2.1M grid values checked, 4,757 of 10,000 lost just above 4, all corruption cases rejected.
- **Local-only build:** build.sh and verify.sh make no network calls and the parser imports no network modules.
- **Download provenance:** the download log shows the current download.sh fetched all 19 files on the first attempt with MD5 and header checks passing.
- **License:** I read the terms in the local v1.1 listing and re-fetched the live listing anonymously. The CC BY 4.0 terms text is unchanged and all files are unrestricted. No script contains credential patterns, and no personal data is emitted.
- **Novelty:** `novelty.py` found no URL matches for the host, DOI or dataset id, and no FTIR, absorbance or soil-spectroscopy family locally or downstream.
- **Bytes (stdlib `struct`):**
  - Decoded samples have realistic DRIFT soil shape.
  - CSV text matches stored float32 within 5.4e-8.
  - float32 exponents span 124 to 128, so the significand is fully used.
  - A nearest-neighbour scan of 300 probes against all samples found closest pairs at 0.0070 mean absolute difference (adjacent plots at the same site). Nothing is near-duplicated.
  - zlib-9 on 300 random samples gives 0.863.
- **Grid profile:** every emitted row has 46-55% of cells on odd grid steps, with no per-country skew.
- **Instrument homogeneity:** noise in the 3800-4000 cm-1 band overlaps across all countries, with no bimodal regime that would point to a second instrument. This supports the Dataverse single-instrument statement against the OSSL "Alpha ZnSe" note. Differences in the 2000-2300 cm-1 band follow quartz-rich versus clayey soils.
- **Minor finding the builder missed:** Zambia icr075957 (source row 1238, next to the excluded rows icr075955 and icr075956) uses only even grid steps, i.e. a 2-replicate mean on a 5e-7 sub-grid. It is a normal, distinct spectrum (range 0.345 to 1.949, 1,746 distinct values), it lies on the family's 2.5e-7 grid and converts losslessly, and it is 1 of 18,247 samples. The manifest phrase "4-replicate means" is therefore true of all but this one spectrum. I recorded it here rather than spend a repair cycle on it.
- **Unverified description detail:** the manifest describes the soil as "air-dried, ground". That comes from ICRAF practice and the OSSL catalogue; the Dataverse page does not say it.
