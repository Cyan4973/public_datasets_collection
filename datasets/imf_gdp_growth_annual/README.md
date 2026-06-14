# IMF GDP Growth Annual

This recipe downloads IMF DataMapper JSON for a fixed country subset and emits one annual GDP growth sample per country.

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
- `gdp_growth_f32`

Missing-value policy:
- filter rows missing numeric annual values
- filter rows whose year is not parseable or outside `1900..2100`
- filter malformed numeric values
- accept whichever IMF JSON substructure yields the largest year-to-value mapping for the requested country and indicator

Run:

```sh
bash datasets/imf_gdp_growth_annual/download.sh
bash datasets/imf_gdp_growth_annual/build.sh
bash datasets/imf_gdp_growth_annual/verify.sh
```

Logs are written under `${DATA_DIR:-.data}/logs/imf_gdp_growth_annual/`.
