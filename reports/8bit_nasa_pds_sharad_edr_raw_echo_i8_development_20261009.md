# MRO SHARAD EDR raw echo int8 development

## Outcome

Accepted `nasa_pds_sharad_edr_raw_echo_i8` from the closed first volume (`MROSH_0001`) of the PDS data set `MRO-M-SHARAD-3-EDR-V1.0`.

This family is distinct from the accepted `nasa_pds_sharad_radargram_f32`:

- **That recipe** holds US RDR radargrams: ground-processed, range-compressed float32 power images from a different data set and different files.
- **This recipe** holds the instrument's own raw received-echo time samples, after on-board summing of 4 echoes and 32→8-bit requantisation, before any ground range compression, Doppler focusing or calibration.

The novelty label is `new_content_same_modality`, not a new modality. Raw radar echo traces already exist at 16 bits (`zenodo_gpr_rd3_i16`, `zenodo_m3d_iwr6843_radar_adc_i16`), and raw 8-bit spacecraft receiver waveforms exist (`nasa_pds_cassini_rpws_wbr_10khz_waveform_u8`).

The zlsim breadth gate measured `OK`, borderline:

- The nearest family by features is `noaa_wcsd_em302_water_column_i8`, at distance 0.0508 against the 0.05 threshold, with 7.6% compression loss.
- Families that compress this material within 3% (SmolLM2 q8 weights, Parkes UWL u8, PUMS age, PacBio IPD) all sit at feature distance 0.0585 or more.

## Source and rights

- **Source:** PDS Geosciences Node, `https://pds-geosciences.wustl.edu/mro/mro-m-sharad-3-edr-v1/mrosh_0001/`.
- **What is fetched:** `label/science8bit.fmt` (MD5 `3bb1ee6b3bb4ed09a6e20f1ab37db517`), 24 detached labels and 24 `*_S.DAT` science-telemetry tables.
- **Pinning:** sizes and MD5s are pinned in `sources.tsv` from the volume MD5 list `mrosh_0001_260909.md5`. The `sources.tsv` SHA-256 is `cbea3799951cdb8bf8063d07cf49b588b24565a6148f81669add0d773497aaeb`.
- **Download:** 948,446,004 bytes of tables.
- **Rights basis:** NASA SMD Scientific Information Policy ("information produced from SMD-funded scientific research activities be made publicly available"). The SPD-41a FAQ says SMD data should be released CC0 where no other restriction exists.
- **Volume documents:** the `AAREADME.TXT` and `VOLDESC.CAT` impose no use restriction.
- **Precedent:** the same basis as the accepted `nasa_pds_sharad_radargram_f32` and the other NASA PDS recipes.
- **Caveat:** SHARAD was provided by the Italian Space Agency (ASI), and the volume carries no explicit CC/PD text.

## Shape and conversion

Each natural record is one EDR observation product. Every `*_S.DAT` row is 3786 bytes:

- a 186-byte ancillary header (`SCIENCE_ANCILLARY.FMT`)
- `ECHO_SAMPLES`: 3600 items of 8-bit `MSB_INTEGER` starting at byte 187

A sample is bytes [186:3786) of every row, copied verbatim and written row-major as a `FILE_RECORDS x 3600` int8 matrix. There is no scaling, remap, cropping, tiling or concatenation, and no auxiliary series.

**Selection** is deterministic, applied to `INDEX.TAB`:

- `INSTRUMENT_MODE_ID` SS19, `DATA_QUALITY_ID` 0, PRF code 700, START–STOP duration 45–70 s: 1,491 candidates.
- Six 30° bands of mid sub-spacecraft latitude, with four evenly spaced picks per band on distinct orbits.

**Labels:** every label asserts RECORD_BYTES 3786, SCIENCE8BIT.FMT, the 'summing 04 … 08-bit precision' mode text, PRI 1428 µs, STATIC compression, no phase compensation, closed-loop tracking disabled, gain 10 and DQ 0.

**Rows:** every non-fill row must have OPERATIVE_MODE 51, the label gain, the science data type and no FPGA error or test flag.

**Fill rows:** three all-zero 3786-byte archive gap-fill rows (rows 9908–9910 of `E_0184801_002`) are preserved as zeros so sample rows stay aligned with table rows. They are counted and capped at 1% per product.

## Accepted output

- Primary series: `sharad_edr_ss19_echo_i8` (int8)
- Primary samples: 24 (products), on 24 distinct orbits 1703–19394, 2006-341 to 2010-258, latitude -85.6° to +87.2°
- Echo rows: 250,514
- Primary values and bytes: 901,850,400
- Minimum sample: 30,250,800 values (8,403 rows)
- Median sample: 37,814,400 values
- Maximum sample: 44,114,400 values (12,254 rows)
- Per-product statistics:
  - range from [-84, 84] to [-115, 115]
  - 160–229 distinct levels
  - mean -1.46 to +0.38 DN
  - standard deviation 13.4–22.2 DN
  - 1.9–3.1% zeros
- Gap-fill rows: 3 (one product); no other constant rows
- All 24 sample SHA-256 values are distinct.
- zlsim: own ratio 1.30, verdict OK, nearest feature distance 0.0508.

## Judge checks

- **Gate:** `gate.py staging/nasa_pds_sharad_edr_raw_echo_i8` passes with no warnings.
- **Verify:** I re-ran `verify.sh`. It is independent of `sharad.py`, re-slices every row with memoryview and byte-compares each sample against the source tables. Result: OK, 24 samples, 901,850,400 bytes.
- **Local-only build and pinning:**
  - `build.sh` reads only `.data/downloads`, and the scripts contain no network or credential use.
  - The `sources.tsv` SHA-256 recomputes to the pinned value.
  - The driver's download log shows all 49 files MD5-matched and `validate: 24 products OK`.
- **Header semantics:** I fetched `SCIENCE_ANCILLARY.FMT` and confirmed the header offsets and flag polarity used by the validator: OPERATIVE_MODE at byte index 26, gain at 27, status word at bytes 44–45, FIFO_FULL=1 meaning no error.
- **Homogeneity:** I scanned every row of all 24 tables. Each product has exactly one OST_LINE value, and products differ only in DATA_TAKE_LENGTH: mode 51, gain 10 and the same control bits throughout.
- **Bytes** (standard-library scripts in `/tmp/autocollect/nasa_pds_sharad_edr_raw_echo_i8/`):
  - No gaps in the [-50, 50] lattice; parity 0.500.
  - Symmetric near-Gaussian histograms with a flat fast-time power profile.
  - Consecutive-row correlation about 0, and per-row std stable along track.
  - No duplicate rows besides the 3 fill rows.
  - Spectral shape (fast-time autocorrelation) varies smoothly with latitude, from signal content within one mode.
- **Novelty:**
  - `novelty.py --url` shows the same host only.
  - The `--type/--instrument/--archive` query matches only `nasa_pds_sharad_radargram_f32`, a different product level and different files.
  - The vocabulary search found raw radar at 16 bits and raw 8-bit receiver waveforms, so the label is `new_content_same_modality`. The README's 'no raw radar-sounder echo at any width' is an overclaim, given the raw GPR traces in `zenodo_gpr_rd3_i16`.
- **Rights:** I confirmed the SMD policy quote and the SPD-41a FAQ's CC0 guidance online, and that `MROSH_0001` `AAREADME.TXT` and `VOLDESC.CAT` contain no restriction. The ASI-provided-instrument caveat is recorded.
