# GDELT Events NumMentions Daily

This recipe downloads a fixed seven-day subset of GDELT daily event exports and emits one sample per day.

Generated series:
- `nummentions_u32`
- `obs_year_u16`
- `obs_month_u8`
- `obs_day_u8`

Usage:

```sh
bash datasets/gdelt_events_nummentions_daily/download.sh
bash datasets/gdelt_events_nummentions_daily/build.sh
bash datasets/gdelt_events_nummentions_daily/verify.sh
```

Logs are written under `${DATA_DIR:-.data}/logs/gdelt_events_nummentions_daily/`.
