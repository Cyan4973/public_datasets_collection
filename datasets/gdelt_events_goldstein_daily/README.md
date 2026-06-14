# GDELT Events Goldstein Daily

This recipe downloads a fixed seven-day subset of GDELT daily event exports and emits one sample per day.

Generated series:
- `goldstein_scale_f32`

Usage:

```sh
bash datasets/gdelt_events_goldstein_daily/download.sh
bash datasets/gdelt_events_goldstein_daily/build.sh
bash datasets/gdelt_events_goldstein_daily/verify.sh
```

Logs are written under `${DATA_DIR:-.data}/logs/gdelt_events_goldstein_daily/`.
