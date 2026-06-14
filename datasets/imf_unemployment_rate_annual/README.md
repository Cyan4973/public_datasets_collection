# IMF Unemployment Rate Annual

This recipe downloads IMF DataMapper JSON for a fixed country subset and emits one annual unemployment rate sample per country.

Selected countries:
- `USA`
- `CHN`
- `IND`
- `BRA`
- `DEU`
- `JPN`
- `MEX`
- `ZAF`

Generated series:
- `unemployment_rate_f32`

Missing-value policy:
- filter rows missing numeric annual values
- filter rows whose year is not parseable or outside `1900..2100`
- filter malformed numeric values
- accept whichever IMF JSON substructure yields the largest year-to-value mapping for the requested country and indicator

Run:

```sh
bash datasets/imf_unemployment_rate_annual/download.sh
bash datasets/imf_unemployment_rate_annual/build.sh
bash datasets/imf_unemployment_rate_annual/verify.sh
```

Logs are written under `${DATA_DIR:-.data}/logs/imf_unemployment_rate_annual/`.
