# JHU COVID-19 Confirmed US Daily

This recipe downloads the Johns Hopkins CSSE US confirmed COVID-19 time-series
CSV and emits one cumulative daily sample per county/FIPS.

Selected scope:
- source file `time_series_covid19_confirmed_US.csv`
- one natural sample per county/FIPS
- cumulative confirmed COVID-19 case counts
- chronological source date-column order
- only county/FIPS samples with at least `1000` parseable daily values by
  default
- non-county buckets such as unassigned or out-of-state rows are rejected

Series emitted:
- `confirmed_cases_u32` (`uint32`, little-endian)

Default quality gates:
- `JHU_COVID19_CONFIRMED_US_MIN_VALUES_PER_SAMPLE=1000`
- `JHU_COVID19_CONFIRMED_US_MIN_SAMPLE_COUNT=500`
- `JHU_COVID19_CONFIRMED_US_MIN_TOTAL_VALUES=500000`
- `JHU_COVID19_CONFIRMED_US_MAX_SAMPLES=100000`

Verified output from the repaired collection:
- `3,206` homogeneous county/FIPS samples
- `3,664,458` uint32 values
- `14,657,832` primary sample bytes
- sample value count range: `1,143` / `1,143` / `1,143` min/median/max
- source CSV has `3,342` rows and `1,143` daily date columns
- build found `3,222` candidate county/FIPS series and rejected `16`
  constant county series
- no fixed-size sharding, padding, interpolation, or synthetic splitting is
  applied

Finite-horizon note:
- Each natural county/FIPS sample has the same `1,143`-day length because the
  JHU source time range is fixed from `2020-01-22` through `2023-03-09`.
- The repair improves this dataset by replacing artificial five-state
  aggregation with thousands of natural homogeneous county records.

Run:

```sh
bash datasets/jhu_covid19_confirmed_us_daily/download.sh
bash datasets/jhu_covid19_confirmed_us_daily/build.sh
bash datasets/jhu_covid19_confirmed_us_daily/verify.sh
```

Logs are written under `${DATA_DIR:-.data}/logs/jhu_covid19_confirmed_us_daily/`.
