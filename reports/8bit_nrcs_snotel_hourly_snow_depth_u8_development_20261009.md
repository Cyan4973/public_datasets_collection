# NRCS SNOTEL hourly snow depth uint8 development

## Outcome

Accepted `nrcs_snotel_hourly_snow_depth_u8`. It holds hourly snow depth in whole inches from the ultrasonic depth sensors of the USDA NRCS SNOTEL (SNTL) network, one uint8 sample per station and water year, for WY2022 to WY2024.

It is the first recipe in the corpus that uses the NRCS National Water and Climate Center archive or the SNOTEL network. The closest family by subject is `noaa_ghcn_daily_snwd_by_station`, which differs on every axis:

| | This recipe | `noaa_ghcn_daily_snwd_by_station` |
|---|---|---|
| Stations | SNOTEL | COOP and first-order (USC/USW), no SNOTEL |
| Cadence | Hourly | Daily |
| Unit | Inches | Millimetres |
| Width | uint8 | int16 |

The downstream `ghcn_snwd` family is also 16-bit daily data. Novelty kind: `new_source`.

## Source and rights

- **Endpoint:** NRCS Report Generator `view_csv`, `customSingleStationReport/hourly/start_of_period/<id>:<ST>:SNTL|id=""|name/2021-10-01,2024-09-30/SNWD::value`. There is one anonymous GET per station.
- **Station list:** 934 SNTL stations, pinned in the recipe as `sntl_stations_20261009.csv`, sha256 `c6af534e…c6b4`. The live list at download time matched it, with 0 additions and 0 removals.
- **Live data, no upstream checksum:** responses are live and provisional, so `download.sh` records the size and sha256 of each response in `download_plan.tsv`, and `verify.sh` re-checks them.
- **Download:** 905 stations returned hourly SNWD and 29 returned none. Total 384,881,772 bytes, fetched fresh by the driver. The README quotes 385,189,662 bytes from an earlier run of the same live source.
- **License:** the catalog.data.gov entry "SNOwpack TELemetry Network (SNOTEL)" (publisher NRCS, USDA) declares License `https://www.usa.gov/publicdomain/label/1.0/` and Access Level public, and lists Snow Depth among its keywords. The data is a U.S. federal government work.
- **Safety:** no credentials, no personal data.

## Shape and conversion

Each natural record is one station × one water year (Oct 1 to Sep 30) of hourly SNWD start-of-period values.

Conversion:
1. Skip `#` lines and require the header `Date,Snow Depth (in)`.
2. Parse each `YYYY-MM-DD HH:MM,value` row and assign it to its water year.
3. Drop empty or absent hours.
4. Write the integer inches unchanged as uint8, in time order.

An auxiliary uint16 series stores the hours since Oct 1 for alignment. It is excluded from acceptance.

Inclusion rules were fixed before the download and are applied per station-year:
- at least 1,000 valid hours
- every value integral and within 0..255; any violation excludes the whole station-year, nothing is clamped
- at least 2 distinct values
- mode share at most 0.80

Station-year decisions:

| Decision | Count |
|---|---|
| Included | 2,625 |
| Too few hours | 49 |
| Mode-dominated | 25 |
| Out of range (all above 255 in, none negative) | 14 |
| Constant | 2 |
| Station with no hourly SNWD | 29 stations |

About half the out-of-range exclusions are genuine deep-snow years, such as 574:CA WY2022 with a maximum of 313 in. The rest are spike hours, such as 1314:OR at 1,245 and 525:WY at 556.

## Accepted output

- Primary samples: 2,625
- Primary values and bytes: 19,342,654
- Sample length: minimum 1,034, median 7,770, maximum 8,784 values
- By water year: WY2022 869, WY2023 880, WY2024 876
- States (13): AK 213, AZ 67, CA 100, CO 342, ID 254, MT 276, NM 83, NV 160, OR 230, SD 6, UT 406, WA 225, WY 263
- Value percentiles: p50 6, p75 32, p90 57, p99 117, p99.9 192; maximum 251
- Mode share per sample: median 0.38, p90 0.55, maximum 0.798. The mode is zero, which is genuine snow-free hours.
- Auxiliary hour-offset output: 2,625 samples, 38,685,308 bytes
- Aggregate SHA-256 of the primary samples, concatenated in sorted name order: `0828736e1cab4b214e10a6c3f38b0577606b6a977d4ba2367adf698874a7b58d`
- zlsim verdict OK. Nearest family is `openf1_throttle_u8` at distance 0.0826 with loss 0.0139.

**Caveats:**
- Hourly data are provisional, and ultrasonic artifacts are kept as published:
  - 0.30% of steps are jumps of 24 in or more
  - stuck echo values occur, such as 185 in UT_0374 WY2024
  - 1,407 isolated zero dropouts occur across 174 samples
- Only 29 samples have a jump rate above 5%, and the worst is 14.8%.

## Judge checks

- **Gate:** `gate.py` passed with 0 warnings.
- **verify.sh:** I re-ran it and it passed in 31 s. It uses a separate code path, re-checks every download hash, re-derives all decisions and compares every file byte for byte.
- **Build uses local files only:** `build.sh` and the build path of `snotel_snwd.py` contain no network calls.
- **Raw format:** I read a raw CSV myself. The metadata reads "Snow Depth, Value, Instantaneous, Inches, SNWD" and the data rows are integers.
- **Independent re-parse:** CA 462 WY2023 (6,806 values) and NM 1173 WY2022 (7,146 values) matched the sample files exactly.
- **Exclusions:** I confirmed that all 14 out-of-range exclusions have values above 255 and none is negative. 1314:OR WY2022 correctly fell under too-few-hours, with 87 valid hours.
- **Full byte scan with stdlib, all 2,625 samples:**
  - steps: 79.5% are 0 and 96.7% are within ±1, consistent with a slowly varying physical depth
  - no exact duplicates and no colliding 3,000-byte prefixes
  - only one sample has a snow-season flat-step share above 97%
- **Rights:** I opened the data.gov entry and confirmed the public-domain label and the NRCS publisher. No script contains credentials.
- **Novelty:** `novelty.py` matched the URL, terms and breadth keys only to the candidate itself, plus the 16-bit GHCN daily SNWD families.
- **Housekeeping:** the stray `scripts/__pycache__/` in the staging recipe should not be promoted.
