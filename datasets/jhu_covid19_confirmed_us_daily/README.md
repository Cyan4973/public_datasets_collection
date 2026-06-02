# JHU COVID-19 Confirmed US Daily

This recipe downloads the Johns Hopkins CSSE US confirmed COVID-19 time-series CSV and emits one cumulative daily sample per selected state.

Selected states:
- `California`
- `Texas`
- `Florida`
- `New York`
- `Illinois`

Series emitted:
- `confirmed_cases_u32`
- `obs_year_u16`
- `obs_month_u8`
- `obs_day_u8`

Run:

```sh
bash datasets/jhu_covid19_confirmed_us_daily/download.sh
bash datasets/jhu_covid19_confirmed_us_daily/build.sh
bash datasets/jhu_covid19_confirmed_us_daily/verify.sh
```

Logs are written under `${DATA_DIR:-.data}/logs/jhu_covid19_confirmed_us_daily/`.
