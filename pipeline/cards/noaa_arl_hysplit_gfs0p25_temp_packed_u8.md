# NOAA ARL HYSPLIT GFS 0.25-degree Meteorology: ARL-Packed Temperature Fields UInt8

- Candidate id: `noaa_arl_hysplit_gfs0p25_temp_packed_u8`
- Width: uint8
- Quantity: Native ARL packed 8-bit codes of GFS temperature on hybrid model levels. Each grid-point byte is a quantized difference from its previously unpacked neighbour: code = round((X - prev) * 2^(7-NEXP)) + 127, with a per-record exponent NEXP and an initial value in the 50-byte label. This is the pinned, machine-facing format HYSPLIT reads.
- Source: https://registry.opendata.aws/noaa-arl-hysplit/
- Resources: https://noaa-oar-arl-hysplit-pds.s3.amazonaws.com/?list-type=2&prefix=gfs0p25/2025/06/, https://noaa-oar-arl-hysplit-pds.s3.amazonaws.com/gfs0p25/2025/06/20250601_gfs0p25, https://noaa-oar-arl-hysplit-pds.s3.amazonaws.com/gfs0p25/2019/06/20190613_gfs0p25
- License: NOAA NODD open data (U.S. Government), attribution requested
- License evidence: https://registry.opendata.aws/noaa-arl-hysplit/ (read via https://s3.amazonaws.com/registry.opendata.aws/noaa-arl-hysplit/index.html)
- License quote: NOAA data disseminated through NODD are open to the public and can be used as desired.
- Natural record: One ARL record: one variable (TEMP) at one model level and one valid time, i.e. the 1440x721 = 1,038,240 one-byte codes that follow the record's 50-byte ASCII label.
- Estimated samples: 110
- Estimated primary values: 114,206,400
- Estimated download bytes: 116,300,000
- Estimated primary bytes: 114,206,400
- Decode path: Fixed-length records of 1,038,290 bytes (50-byte label + 1,038,240 codes). Each daily gfs0p25 file (2,898,905,680 bytes) holds 8 valid times x 349 records: INDX, 18 surface variables, then 55 levels x (TEMP, UWND, VWND, WWND, RELH, PRES). TEMP at level k (0-54) for time t starts at byte (t*349 + 19 + 6*k) * 1,038,290. download.sh range-GETs the INDX record (to verify the variable table and grid '440721' / 56 levels) and each selected TEMP record. build.sh checks each label (date fields, level, 'TEMP', NEXP, PREC, VAL1) and emits the 1,038,240 code bytes as uint8. Label fields are auxiliary. Pure stdlib only.
- Novelty kind: new_modality
- Novelty evidence: novelty.py --url https://noaa-oar-arl-hysplit-pds.s3.amazonaws.com/gfs0p25/ with terms hysplit / 'ARL packed' / gfs0p25 / gdas, plus a separate check on gfs / grib / 'global forecast system': no matches in recipes, registry, ledger, downstream or downstream_registry. There is no NWP / weather-model-output family at 8-bit locally or downstream, which is the driver's 'weather and climate model output' focus.
- Homogeneity: One variable (TEMP) only. Do not mix UWND/VWND/WWND/RELH/PRES or surface fields, whose difference statistics differ. One archive (gfs0p25, same 1440x721 grid and 56-level layout). Suggested selection: all 55 upper levels at 00 UTC on two seasonally separated dates (e.g. one January and one July day) = 110 records. The per-record exponent varies by level but the code semantics are identical.
- Risks: The judge may treat DPCM-packed codes as a codec artifact rather than a physical quantity. Counter-precedent: a pinned, decades-stable, machine-facing operational format, like the accepted GGUF Q8_0 quantized weights or NIDS level codes. Codes cluster near 127 (low entropy, still genuine). Daily files are 2.9 GB, so only range GETs are allowed (110 requests of about 1 MB). The grid label uses an extended 'A@' code for 1440 columns. The ARL archive is converted from NCEP GFS output (derived operational product). Lowest-confidence candidate of this set.
- Probe evidence: Bucket noaa-oar-arl-hysplit-pds lists anonymously (edas, edas40, fnl, gdas0p5, gdas1, gfs0p25, hrrr, nam12, ...). Every gfs0p25 daily file is exactly 2,898,905,680 bytes = 8 x 349 x 1,038,290. A 4 KB range read of 20190613_gfs0p25 shows label '19 613 0 0 0A@INDX ...' and an INDX body 'GFSQ ... 440721 56 4334 ... 18 PRSS MSLE ... SHGT .99990 6TEMP UWND VWND WWND RELH PRES ...'. That is 18 surface variables and 6 variables per hybrid level, confirming the fixed record arithmetic. gdas1 weekly files (598,888,640 bytes; 360x181 records) were also verified as an alternative. License read from the S3-hosted registry page.

Proposed by the autocollect scout on 2026-10-05 (transcript `.data/pipeline/logs/scout_8bit/scout.20261005_194855.jsonl`).
