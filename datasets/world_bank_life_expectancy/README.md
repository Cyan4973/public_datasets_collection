# World Bank Life Expectancy

This recipe collects annual World Bank indicator values for a fixed set of
countries and converts them into raw numeric samples.

Selected scope:
- indicator: `SP.DYN.LE00.IN`
- countries:
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
- one output sample per country per series

Series emitted by `build.sh`:
- `world_bank_value_f64` (`float64`, little-endian)
- `obs_year_u16` (`uint16`, little-endian)

Notes:
- Source data comes from the World Bank indicator API.
- `download.sh` validates the outer payload shape and requires at least one
  row with `date` and `value`.
- Missing-value policy: rows with null values, malformed years, or malformed
  numeric values are filtered.

Usage:

```sh
bash datasets/world_bank_life_expectancy/download.sh
bash datasets/world_bank_life_expectancy/build.sh
bash datasets/world_bank_life_expectancy/verify.sh
```
