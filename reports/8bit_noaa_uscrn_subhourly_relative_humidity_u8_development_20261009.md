# NOAA USCRN subhourly relative humidity uint8 development

## Outcome

I accepted `noaa_uscrn_subhourly_relative_humidity_u8` from the official NOAA NCEI U.S. Climate Reference Network `subhourly01` product, 2024 directory.

This is the first USCRN material in the corpus at any width. The nearest relative-humidity material is:
- `nasa_power_daily_humidity` (f64): daily, modelled.
- downstream `open_meteo_relative_humidity_f32`: hourly reanalysis.
- `appliances_energy_uci` (f64): indoor sensors.

This recipe is measured 5-minute outdoor RH at 1.5 m from a reference-grade station network, kept in the archive's native integer-percent form.

## Source and rights

- Source: https://www.ncei.noaa.gov/pub/data/uscrn/products/subhourly01/2024/
  - 159 station-year files (24 AK, 2 HI, 1 ON, 132 CONUS including 19 Alabama regional sites).
  - 2,252,441,520 bytes in total.
- Format: CRNS0101-05 fixed-width text, 23 columns, 135-byte lines.
  - RELATIVE_HUMIDITY is field 16 (cols 95-99, %). RH_FLAG is field 17 (col 101).
  - The column layout is validated against `HEADERS.txt` and `readme.txt`.
- Pinning: per-file sizes and SHA-256 values are in `sources.tsv`, and `download.sh`, `build.sh` and `verify.sh` all enforce them. NCEI revises files in place, so an upstream revision fails loudly and needs a deliberate re-pin.
- License: U.S. Government work (17 U.S.C. 105).
  - The NCEI ISO record `gov.noaa.ncdc:C00546` covers USCRN sub-hourly, hourly, daily and monthly products.
  - Its only constraints are a citation request (Palecki et al. 2013, doi:10.7289/V5H13007) and NOAA's distribution-liability disclaimer. It states no use restriction.

## Shape and conversion

- Natural record: one station-year file. One sample is that file's RH values in UTC time order.
- Kept rows: `RH_FLAG == 0` and `0 <= RH <= 100`. Each value is written unchanged as one uint8, with no rescale or rounding.
- Dropped rows (not imputed):
  - 714,699 rows with the -9999 sentinel;
  - 105,738 flag-3 rows, including Alaska winter -1 values.
  - No flag-1 or out-of-range flag-0 rows occurred.
- Gaps break the strict 5-minute lattice.
- No auxiliary series is emitted.
- `AL_Brewton_3_NNE` and `AL_Highland_Home_2_S` are -9999 for every 2024 row. Both scripts exclude them by the 1,000-value floor.
- Known blemish: `AK_Fairbanks_11_NE` reports flag-0 values of about 0-3 % from February to August 2024, about 32k values. This is a failed sensor that passed NCEI QC. It is documented and kept as archived; it is 0.2 % of the total.

## Accepted output

- Source files validated: 159 (16,684,752 rows)
- Excluded station-years: 2
- Primary samples: 157
- Primary values: 15,864,315
- Primary bytes: 15,864,315
- Minimum sample: 13,668 values (OR_Corvallis_10_SSW)
- Median sample: 105,324 values
- Maximum sample: 105,384 values
- Value range: 0-100. Per-sample distinct values: min 41, median 87.
- Largest single-value share: 36.5 % (LA_Monroe_26_N, value 100). No sample is above 50 %.
- Aggregate SHA-256 of samples concatenated in sorted filename order: `f184fd2bbbf54e858a5d00f401d3ff450abcbb525e933e71764dc4537beac970`
- Measured breadth (zlsim): OK. The nearest family is `downstream:video_chroma_cr_u8` at distance 0.0831, with compressor loss 0.2846.

## Judge checks

- **Gate:** `gate.py` passed with no warnings.
- **verify.sh:** I re-ran it; verify ok. It re-derives every sample from fixed-width columns, independently of build's whitespace parser, and enforces SHA-256 pins on all 159 local files.
- **Provenance:** `download.sh` (mtime 11:05) predates the 11:15 download run. The `sources.tsv` pins equal the run's `download_plan.tsv` for all 159 files.
- **Local-only build:** `build.sh` and `verify.sh` make no network calls and contain no credentials.
- **Bytes:**
  - The first sample bytes of `AZ_Tucson_11_W` equal raw field 16.
  - Tucson's June mean by UTC hour peaks at 34 % at 12Z (dawn) and bottoms at 13 % at 20-21Z, which is physically correct.
  - Dry-site low values (Stovepipe Wells, Mauna Loa, Mercury) and humid-site saturation (Monroe, Sitka, Toolik) are natural.
- **Duplicates:** co-located station pairs agree exactly on only 6-20 % of aligned timestamps, with mean absolute differences of 2.1-4.6 %. They are independent sensors, not near-duplicates.
- **Rights:** I fetched the ISO record myself and confirmed the citation and disclaimer text and that it covers the sub-hourly products.
- **Novelty:** `novelty.py` with `--url` (subhourly01), `--terms` (USCRN, climate reference network, subhourly, CRNS0101) and `--type/--instrument/--archive` found no USCRN material locally, in the registry or downstream. Same-path hits are only GHCN and ISD under `/pub/data`.
- **Minor discrepancy:** the builder said there was one Last-Modified log note. There are many, all 4-5 h offsets between the listing's US Eastern time and the GMT header, so they are benign under SHA-256 pinning.
