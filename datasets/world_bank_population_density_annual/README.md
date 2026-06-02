# World Bank Population Density

This recipe collects annual World Bank indicator values for a fixed set of
countries and converts them into raw numeric samples.

Selected scope:
- indicator: `EN.POP.DNST`
- countries:
  - `CHN`
  - `IND`
  - `BRA`
  - `DEU`
  - `JPN`
  - `NGA`
  - `MEX`
  - `FRA`
  - `ZAF`
- one output sample per country per series

Series emitted by `build.sh`:
- `population_density_f64` (`float64`, little-endian)
- `obs_year_u16` (`uint16`, little-endian)

Notes:
- Source data comes from the World Bank indicator API.
- `download.sh` validates the outer payload shape, rejects World Bank error
  payloads, and requires at least one retained non-null value row.
- Missing-value policy: rows with null values, malformed years, or malformed
  numeric values are filtered.

Usage:

```sh
bash datasets/world_bank_population_density_annual/download.sh
bash datasets/world_bank_population_density_annual/build.sh
bash datasets/world_bank_population_density_annual/verify.sh
```
