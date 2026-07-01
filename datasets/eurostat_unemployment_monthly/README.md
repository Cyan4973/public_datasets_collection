# Eurostat Unemployment Monthly

This recipe downloads a Eurostat JSON-stat query for monthly unemployment
rates and emits one homogeneous observation-column sample.

The query fixes:
- `unit=PC_ACT`

It leaves `s_adj`, `age`, `sex`, and `geo` open, so all returned adjustment
statuses, age groups, sex categories, geographies, and months are retained
when Eurostat publishes a numeric value.

Generated series:
- `unemployment_rate_f32` primary monthly unemployment-rate values
- `eurostat_unemployment_s_adj_index` auxiliary adjustment-status ordinal
- `eurostat_unemployment_age_index` auxiliary age-category ordinal
- `eurostat_unemployment_sex_index` auxiliary sex-category ordinal
- `eurostat_unemployment_geo_index` auxiliary geography-category ordinal
- `eurostat_unemployment_month_ordinal` auxiliary month ordinal

Missing-value policy:
- filter missing values from sparse Eurostat `value` payloads
- filter malformed numeric values
- filter malformed time keys
- treat non-`s_adj`, non-`age`, non-`sex`, non-`geo`, and non-`time`
  dimensions as fixed at their only selected position

Axis category mappings are written to
`${DATA_DIR:-.data}/filtered/eurostat_unemployment_monthly/dimension_categories.json`.

Run:

```sh
bash datasets/eurostat_unemployment_monthly/download.sh
bash datasets/eurostat_unemployment_monthly/build.sh
bash datasets/eurostat_unemployment_monthly/verify.sh
```

Logs are written under `${DATA_DIR:-.data}/logs/eurostat_unemployment_monthly/`.
