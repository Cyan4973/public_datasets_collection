# JHU COVID-19 Deaths US Daily

This recipe downloads the Johns Hopkins CSSE US deaths COVID-19 time-series CSV and emits one cumulative daily sample per selected state.

Selected states:
- `California`
- `Texas`
- `Florida`
- `New York`
- `Illinois`

Series emitted:
- `death_counts_u32`

Run:

```sh
bash datasets/jhu_covid19_deaths_us_daily/download.sh
bash datasets/jhu_covid19_deaths_us_daily/build.sh
bash datasets/jhu_covid19_deaths_us_daily/verify.sh
```

Logs are written under `${DATA_DIR:-.data}/logs/jhu_covid19_deaths_us_daily/`.
