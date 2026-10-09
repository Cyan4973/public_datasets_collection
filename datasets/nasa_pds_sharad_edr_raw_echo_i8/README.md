# MRO SHARAD EDR Raw Echo Samples, Mode SS19 (presum 4, 8-bit), Int8

This recipe collects 24 complete MRO SHARAD (Shallow Radar) EDR
science-telemetry products from NASA PDS (`MRO-M-SHARAD-3-EDR-V1.0`, volume
`MROSH_0001`). Each sample is one product's matrix of raw received-echo time
samples: signed 8-bit antenna-voltage data numbers exactly as the instrument
produced them, after summing 4 echoes on board and requantizing from 32 to 8
bits (mode SS19). No ground processing such as range compression, Doppler
focusing or calibration has been applied.

- Series: `sharad_edr_ss19_echo_i8`. It is the only series and is primary.
  Type is `int8`, with one sample per product of shape `FILE_RECORDS x 3600`,
  row-major (echo row, fast-time sample).
- Scope: 24 products on 24 distinct orbits (1703–19394), from 2006-341 to
  2010-258. There are four products in each 30° band of sub-spacecraft
  latitude, covering -85.6° to +87.2°.
  - 250,514 echo rows, 901,850,400 values (bytes).
  - 948,446,004 bytes of `*_S.DAT` tables to download.
- Sample sizes range from 8,403 to 12,254 rows (30.2–44.1 MB). Product
  durations are 48–70 s at about 175 rows/s.

## Source

PDS Geosciences Node:
`https://pds-geosciences.wustl.edu/mro/mro-m-sharad-3-edr-v1/mrosh_0001/`.
Each product is a detached PDS3 label `<product>.lbl` plus two tables:

- `<product>_s.dat`: the science telemetry table. It has fixed 3786-byte
  rows: a 186-byte ancillary header (`SCIENCE_ANCILLARY.FMT`) followed by
  `ECHO_SAMPLES` (`SCIENCE8BIT.FMT`: 3600 items x 8-bit `MSB_INTEGER`,
  starting at byte 187).
- `<product>_a.dat`: the ground-generated auxiliary geometry table. It is not
  fetched.

`sources.tsv` pins the following for each product:

- the label and table paths
- orbit, start and stop time, and start/stop latitude and longitude
- `FILE_RECORDS` and the table size (= `FILE_RECORDS x 3786`)
- the table MD5 and label MD5, both taken from the volume's published MD5
  list `mrosh_0001_260909.md5`
- `MANUAL_GAIN_CONTROL`

`discover.sh` produced it on 2026-10-09. It is metadata only: `INDEX.TAB`,
the MD5 list, 24 labels, and three single-row range probes per product.

### Selection

`MROSH_0001` is the closed first volume (2006-12 to 2010-11). Its index lists
7,215 SS19 products, all at PRF code 700. The rule, implemented in
`scripts/sharad.py select`, is:

1. Keep products with `INSTRUMENT_MODE_ID = SS19`, `DATA_QUALITY_ID = 0`, PRF
   code `700`, and a START–STOP duration of 45–70 s. That leaves 1,491
   candidates. The duration window keeps the total under 1 GB with
   about 24 natural products.
2. Assign each product to one of six 30° bands by mid sub-spacecraft latitude.
3. Within each band, sort by (orbit, product ID) and take 4 products at
   positions `floor((k+0.5) n/4)`. If a position's orbit has already been
   chosen, step forward to the next product.

Every selected label asserts one acquisition regime:

- `RECORD_BYTES = 3786`, `^STRUCTURE = "SCIENCE8BIT.FMT"`
- `INSTRUMENT_MODE_ID = SS19`, with the mode text "summing 04 sequential
  echoes, and converting the result from 32-bit precision to 08-bit precision"
- `PULSE_REPETITION_INTERVAL = 1428 us`
- `COMPRESSION_SELECTION_FLAG = STATIC`, `NO COMPENSATION`, closed-loop
  tracking `DISABLED`
- `MANUAL_GAIN_CONTROL = 10`
- `DATA_QUALITY_ID = 0`

The following are excluded:

- the 4-bit and 6-bit formats (`science4bit.fmt`/`science6bit.fmt`)
- all other presum modes (SS04, SS05, SS11, …)
- receive-only modes
- the later volumes `MROSH_0002`–`0004`. `MROSH_0004` is still growing.

## Conversion

1. `download.sh` does the following:
   - checks the `sources.tsv` SHA-256
   - fetches `science8bit.fmt`, the 24 labels, and the 24 `_s.dat` tables
     (resumable `curl -C -` with a stall-based speed limit)
   - checks sizes and MD5s against the volume MD5 list
   - runs `scripts/sharad.py validate`, which checks the format file layout,
     every label field listed above, and every row header:
     - `OPERATIVE_MODE` byte = 51 (SS19)
     - gain byte = label gain
     - `SCIENTIFIC_DATA_TYPE` = science
     - no `DMA_ERROR`, `TC_OVERRUN`, `FIFO_FULL` or `TEST` flag
2. `build.sh` re-runs the label and row checks. It then writes bytes
   `[186:3786)` of every row, in row order, to
   `samples/<id>/sharad_edr_ss19_echo_i8/NN_<product>.i8`.
   - The stored bytes are the archive's two's-complement int8 values, copied
     verbatim. Byte order does not matter at 8 bits.
   - No scaling, re-centring, cropping, tiling or concatenation is applied.
   - `index/<id>/samples.jsonl` records, for each sample: shape, product,
     orbit, times, latitude/longitude, gain, SHA-256, min/max/mean, distinct
     levels, zero fraction and constant-row count.
3. `verify.sh` (`scripts/verify.py`) is independent of `sharad.py`. It does
   the following:
   - re-reads the labels with its own regexes
   - re-slices every row with `memoryview` and byte-compares the result with
     the emitted sample
   - recomputes the statistics by a different method
   - checks the index fields, uniqueness, and the manifest `sample_count` and
     `total_size_bytes`

## Missing values and degeneracy

The format declares no fill value. The archive does contain gap-fill rows,
in which all 3786 bytes (header and echo) are zero. The full download found
exactly 3 such rows: rows 9908–9910 of `E_0184801_002` (product 03), a
`DATA_QUALITY_ID = 0` product. No other product has any.

- Fill rows are **preserved in place** as 3600 zeros, so sample rows stay
  1:1 with source table rows.
- They are counted per sample as `zero_fill_rows` and capped at 1% of a
  product's rows.
- The per-row mode, gain and flag checks are skipped only for these all-zero
  rows. Any other anomalous row is fatal, and none occurs.

No rows or samples are dropped or imputed, and 0 is otherwise an ordinary
sample level. Constant echo rows are kept and counted. Build and verify both
reject a product in any of these cases:

- it has more than 5% constant rows
- it has more than 1% all-zero fill rows
- it has fewer than 32 distinct levels
- one level holds more than 50% of its values
- verify only: its standard deviation is below 2 DN

Range probes before download, on rows 10,000–10,040 of
`E_0168901_001` and on the first, middle and last row of all 24 selected
products, showed zero-mean echoes spanning about -83..+83 with 115–127
distinct levels per row and about 2% zeros. Download-time validation of all
24 tables found 160–229 distinct levels per product and zero fractions of
1.9–3.1%. The only constant rows are the 3 fill rows.

Realized build (2026-10-09; `verify.sh` OK, gate PASS):
- 24 samples, 250,514 echo rows, 901,850,400 values. Per sample:
  - 30,250,800–44,114,400 values; the median is 37,814,400.
  - value range from [-84, 84] to [-115, 115]
  - 160–229 distinct levels
  - mean -1.46 to +0.38 DN
  - standard deviation 13.4–22.2 DN
  - 1.9–3.1% zeros
- All 24 SHA-256 values are distinct.

## License

These are NASA PDS public mission data. The NASA SMD Scientific Information
Policy states: "It is Science Mission Directorate (SMD) policy, consistent
with NASA and Federal policies, that information produced from SMD-funded
scientific research activities be made publicly available."

- The data are served anonymously by the PDS Geosciences Node.
- SHARAD was provided by the Italian Space Agency (ASI). The rights basis is
  the NASA PDS public archive, the same basis as the accepted
  `nasa_pds_sharad_radargram_f32`.
- The volume carries no explicit CC/PD licence text.
- Cite the SHARAD team (PI R. Seu), the data set ID, the volume and the
  product IDs.

## Novelty and caveats

- **Novelty:** this is a new quantity. The corpus has no raw radar-sounder
  echo telemetry at any width. The other SHARAD recipe is
  `nasa_pds_sharad_radargram_f32`. It holds US RDR radargrams, which are
  ground-processed, range-compressed float32 power images from a different
  data set and different files. Raw radar data elsewhere is 16-bit only
  (Svalbard GPR i16 downstream, TI FMCW ADC `zenodo_m3d_iwr6843_radar_adc_i16`).
- **Same instrument line:** a judge may weigh `mro_sharad` as already
  present.
- **Byte gate (zlsim, 2026-10-09): verdict `OK`, not `STRONG`, and
  borderline.**
  - The nearest family is `noaa_wcsd_em302_water_column_i8`, at feature
    distance 0.0508 (threshold 0.05) and compression loss 7.6%.
  - Several families compress this material within 3% (loss 0.25–0.46%):
    SmolLM2 q8 weights, Parkes UWL u8 and PUMS age. Their feature distances
    are 0.059–0.070, just outside the threshold.
  - ASCAD: distance 0.073, loss 23%.
  - The material is therefore compression-similar to other near-Gaussian
    8-bit streams and is novel mainly by a narrow statistical margin. Its own
    ratio is 1.30.
- **Sample count:** 24 natural products, which is above the soft target of
  about 20. The source offers thousands, but the 1 GB cap and about 40 MB
  products bound the count. The total of 0.90 GB is close to the cap.
- **Era:** 18 of the 24 products come from 2006–2008 (9 from 2006). Early-mission products
  are often exactly 60 s, which favours that period in the 45–70 s window.
