# OWID CO2 Annual

This recipe downloads the Our World in Data `owid-co2-data.csv` extract and emits one annual sample per selected country for the chosen numeric column.

Selected countries:
- `USA`
- `CHN`
- `IND`
- `BRA`
- `DEU`
- `JPN`
- `NGA`
- `MEX`
- `FRA`
- `ZAF`

Series emitted:
- `owid_value_f32`

Run:

```sh
bash datasets/owid_co2_per_gdp_annual/download.sh
bash datasets/owid_co2_per_gdp_annual/build.sh
bash datasets/owid_co2_per_gdp_annual/verify.sh
```

Logs are written under `${DATA_DIR:-.data}/logs/owid_co2_per_gdp_annual/`.
