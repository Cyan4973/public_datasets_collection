# JHU COVID-19 Confirmed Global Daily

This recipe downloads the Johns Hopkins CSSE global confirmed COVID-19 time-series CSV and emits one cumulative daily sample per selected country.

Selected countries:
- `US`
- `India`
- `Brazil`
- `France`
- `Germany`

Series emitted:
- `confirmed_cases_u32`
- `obs_year_u16`

Run:

```sh
bash datasets/jhu_covid19_confirmed_global_daily/download.sh
bash datasets/jhu_covid19_confirmed_global_daily/build.sh
bash datasets/jhu_covid19_confirmed_global_daily/verify.sh
```

Logs are written under `${DATA_DIR:-.data}/logs/jhu_covid19_confirmed_global_daily/`.
