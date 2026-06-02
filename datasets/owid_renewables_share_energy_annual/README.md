# OWID Renewables Share Energy Annual

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
- `renewables_share_energy_f32`
- `obs_year_u16`

Run:

```sh
bash datasets/owid_renewables_share_energy_annual/download.sh
bash datasets/owid_renewables_share_energy_annual/build.sh
bash datasets/owid_renewables_share_energy_annual/verify.sh
```

Logs are written under `${DATA_DIR:-.data}/logs/owid_renewables_share_energy_annual/`.
