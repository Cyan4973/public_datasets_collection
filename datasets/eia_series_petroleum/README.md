# EIA Petroleum Spot Prices

Paginated daily observations from the EIA petroleum spot-price endpoint:

- `https://api.eia.gov/v2/petroleum/pri/spt/data/`

The primary payload is the native `value` field, grouped into one sample per EIA
series and split by reported unit:

- `eia_petroleum_spot_price_usd_per_gallon_f64`
- `eia_petroleum_spot_price_usd_per_barrel_f64`

The date axis is emitted as auxiliary ordinal-day samples. Product names, area
names, and other text metadata are retained only in the sample index metadata;
text lengths are not emitted.
