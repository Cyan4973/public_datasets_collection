# NOAA USCRN subhourly relative humidity, 2024 (uint8)

This recipe takes 5-minute relative humidity from the NOAA U.S. Climate Reference
Network (USCRN) `subhourly01` product. NCEI archives RH as an integer percent
(0-100), so each value fits in one unsigned byte. One sample is one station-year:
all 2024 values from one station that pass QC, kept in UTC time order.

- Source: <https://www.ncei.noaa.gov/pub/data/uscrn/products/subhourly01/2024/>.
  The recipe takes the whole directory: 159 station files, 2,252,441,520 bytes.
  That is 24 AK, 2 HI, 1 Ontario (Egbert) and 132 CONUS stations, including
  the 19 Alabama regional sites.
- Layout: `HEADERS.txt` and `readme.txt` describe 23 fixed-width columns, each
  line 135 bytes. RELATIVE_HUMIDITY is field 16 (cols 95-99, %). RH_FLAG is
  field 17 (col 101): 0 = good, 1 = field-length overflow, 3 = erroneous.
  Missing values are -9999.
- License: U.S. Government public domain (17 U.S.C. 105). The NCEI ISO record
  `gov.noaa.ncdc:C00546` carries only a citation request
  (Palecki et al. 2013, doi:10.7289/V5H13007) and NOAA's no-warranty and
  liability disclaimers. It states no use restriction.

## Realized output (build of 2026-10-09)

- 157 samples, 15,864,315 bytes (= values), from 16,684,752 source rows.
  Rows kept: 15,864,315. Dropped: 714,699 missing (-9999) and 105,738
  flag 3. No rows had flag 1 or a flag-0 value outside 0-100.
- Two stations are excluded because every 2024 row is -9999:
  `AL_Brewton_3_NNE` and `AL_Highland_Home_2_S`. Both fall below the
  1,000-value floor.
- Sample length: min 13,668, median 105,324, max 105,384 values.
- Short samples, mostly from -9999 runs where the RH sensor was not
  reporting:
  - OR_Corvallis_10_SSW: 13,668
  - AL_Valley_Head_1_SSW: 13,968
  - AL_Scottsboro_2_NE: 16,164
  - AL_Selma_6_SSE: 22,044
  - MA_Blue_Hill_0_W: 30,204 (partial-year file)
  - FL_Sebring_23_SSE: 65,271 (40,112 flag-3 rows)
  - AK_Fairbanks_11_NE: 69,215 (36,129 flag-3 rows, the winter -1 values)
  - AK_Cordova_14_ESE: 69,377
- No sample has one value covering more than 50 %. The largest single-value
  shares are LA_Monroe_26_N (36.5 % at 100), TX_Port_Aransas_32_NNE
  (27.6 % at 100), AK_Toolik_Lake_5_ENE (23.5 % at 100) and
  AK_Sitka_1_NE (20.4 % at 96). AK_Fairbanks_11_NE has 15.3 % at 1, from
  the degraded-sensor period described below.
- Per-file SHA-256 values from this download are now pinned in
  `sources.tsv`. `download.sh`, `build.sh` and `verify.sh` all reject a
  file whose hash differs.

## Conversion

1. `download.sh` fetches the 159 files listed in `sources.tsv`, with pinned
   names and byte sizes. It uses resumable curl with stall detection. It also
   fetches `HEADERS.txt` and `readme.txt` and checks that the column order and
   the documented RH and RH_FLAG column positions are unchanged. Each file
   must pass these checks:
   - every line is 135 bytes and has 23 fields;
   - the file has a single WBANNO;
   - UTC dates fall in 2024, plus the 2025-01-01 00:00 closing interval;
   - RH is an integer and RH_FLAG is a single digit;
   - line count = size / 135.

   It records per-file SHA-256 and Last-Modified in
   `downloads/<id>/download_plan.tsv`.
2. `build.sh` (`scripts/uscrn_rh.py build`) splits each line on whitespace and
   requires strictly increasing UTC timestamps. It keeps rows where
   `RH_FLAG == 0` and `0 <= RH <= 100`, and writes each kept value as one
   `uint8`. Output goes to
   `samples/<id>/uscrn_rh_5min_u8/<station>.bin`. Dropped rows are counted per
   category (missing -9999, flag 3, flag 1, flag-0 out of range) for each
   station. The counts go to `filtered/<id>/ingest_stats.json` and to the
   index (`rows_total`, `rows_dropped`).
3. `verify.sh` re-derives every sample independently from the fixed-width
   columns (cols 95-99, col 101) and checks:
   - sample bytes match byte for byte;
   - index fields and sample hashes are correct;
   - manifest `sample_count` and `total_size_bytes` match the output;
   - repository floors are met;
   - no sample is constant and no two samples are identical.

   It also reports any sample where one value covers more than 50 %. Both
   scripts would drop a station-year with fewer than 1,000 valid values.

No mask or other auxiliary series is emitted. Gaps from dropped rows break
the strict 5-minute lattice. The values are in time order, but they are not
on an evenly spaced lattice.

## Honest caveats

- Integer percent is how NCEI archives the value. The sensor resolves finer
  than 1 %, and the recipe does no rescaling.
- Only 1 of 23 text columns is used. Roughly 16 MB of RH comes from about
  2.25 GB of text. No leaner source exists: there is no column projection and
  no gzip transfer, and the yearly snapshots are multi-GB zips.
- Probes found these station patterns:
  - Alaska winter months at some stations (e.g. Fairbanks, January) are all
    `-1` with flag 3. They are dropped, so those samples are shorter.
  - Fairbanks 11 NE reports flag-0 values of 0-6 % from about January to
    mid-August 2024, which points to a degraded sensor. Values are normal
    after late August. These values passed NCEI QC and are kept as archived,
    with no extra filtering for one station.
  - Humid sites (Sitka, Hilo, Asheville) sit at 90-100 % for long stretches.
    `verify.sh` reports samples where one value dominates.
- `MA_Blue_Hill_0_W` covers only part of the year: 30,288 rows instead of
  105,408.
- NCEI revises station files in place; listing timestamps run from 2025-06 to
  2026-10. Sizes and SHA-256 values are pinned, so a later upstream revision
  makes `download.sh` fail with a SHA-256 mismatch. To accept the new data,
  re-pin `sources.tsv` deliberately and rebuild.

## Run

```bash
bash staging/noaa_uscrn_subhourly_relative_humidity_u8/download.sh
bash staging/noaa_uscrn_subhourly_relative_humidity_u8/build.sh
bash staging/noaa_uscrn_subhourly_relative_humidity_u8/verify.sh
```
