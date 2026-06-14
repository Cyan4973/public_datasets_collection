# Eurostat Female Female Unemployment Monthly

This recipe downloads a fixed Eurostat JSON-stat query for five countries and emits one monthly unemployment-rate sample per country.

Selected countries:
- `DE`
- `FR`
- `IT`
- `ES`
- `NL`

Generated series:
- `unemployment_rate_f32`

Missing-value policy:
- filter missing values from sparse Eurostat `value` payloads
- filter malformed time keys
- filter malformed numeric values
- treat non-`geo` and non-`time` dimensions as fixed at their only selected position

Run:

```sh
bash datasets/eurostat_female_unemployment_monthly/download.sh
bash datasets/eurostat_female_unemployment_monthly/build.sh
bash datasets/eurostat_female_unemployment_monthly/verify.sh
```

Logs are written under `${DATA_DIR:-.data}/logs/eurostat_female_unemployment_monthly/`.
