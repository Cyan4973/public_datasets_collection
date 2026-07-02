# OWID CO2 Source Emissions Annual Float32

`owid_co2_source_emissions_annual_f32` emits homogeneous annual CO2 source
emissions columns from the public Our World in Data CO2 CSV.

Each primary sample is one published source-emissions column over ISO-country
annual rows, sorted by `(iso_code, year)`. The recipe keeps only native numeric
emissions quantities and does not emit text-derived fields, country identifiers,
shares, per-capita values, or energy fields.

Series emitted:
- `owid_coal_co2_mt_f32`
- `owid_oil_co2_mt_f32`
- `owid_gas_co2_mt_f32`
- `owid_cement_co2_mt_f32`
- `owid_flaring_co2_mt_f32`

Run:

```sh
bash datasets/owid_co2_source_emissions_annual_f32/download.sh
bash datasets/owid_co2_source_emissions_annual_f32/build.sh
bash datasets/owid_co2_source_emissions_annual_f32/verify.sh
```

Logs are written under
`${DATA_DIR:-.data}/logs/owid_co2_source_emissions_annual_f32/`.
