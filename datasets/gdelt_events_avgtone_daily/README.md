# GDELT Events AvgTone Daily

This recipe downloads a fixed seven-day subset of GDELT daily event exports and emits one sample per day.

Generated series:
- `avgtone_f32`

Usage:

```sh
bash datasets/gdelt_events_avgtone_daily/download.sh
bash datasets/gdelt_events_avgtone_daily/build.sh
bash datasets/gdelt_events_avgtone_daily/verify.sh
```

Logs are written under `${DATA_DIR:-.data}/logs/gdelt_events_avgtone_daily/`.
