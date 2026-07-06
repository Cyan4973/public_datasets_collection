# EIA Petroleum Barrel Prices

This recipe broadens the earlier EIA spot-price probe by discovering EIA
petroleum price API leaves, then retaining only crude/oil price series reported
in dollars per barrel.

The primary emitted family is:

- `eia_petroleum_crude_oil_price_usd_per_barrel_f64`

The build step keeps one natural sample per retained EIA series/frequency pair.
It intentionally does not shard these time series before evaluation.

Current verified output:

- `16` samples
- `33,764` values
- `270,112` bytes
- frequencies: `daily`, `weekly`, `monthly`
- endpoints retained: `petroleum/pri/spt`, `petroleum/pri/fut`

`download.sh` is proxy-aware and accepts overrides:

- `EIA_BARREL_PRICE_ENDPOINTS`: route list, default
  `petroleum/pri/spt petroleum/pri/fut petroleum/pri/rac`
- `EIA_BARREL_PRICE_DISCOVER=1`: discover leaves from `EIA_BARREL_PRICE_ROOTS`
  instead of using the narrow default endpoint list
- `EIA_BARREL_PRICE_ROOTS`: discovery roots, default `petroleum/pri`
- `EIA_BARREL_PRICE_FREQUENCIES`: default `daily weekly monthly`
- `EIA_BARREL_PRICE_MAX_RECORDS_PER_ENDPOINT_FREQ`: default `75000`
- `EIA_BARREL_PRICE_CONNECT_TIMEOUT`: curl connect timeout, default `10`
- `EIA_BARREL_PRICE_MAX_TIME`: curl per-request maximum time, default `120`
- `EIA_BARREL_PRICE_HTTP_RETRIES`: short manual retries for network and 5xx
  failures, default `2`; HTTP 429 is not retried
- `EIA_API_KEY`: default `DEMO_KEY`

Run order:

```bash
bash datasets/eia_petroleum_barrel_prices/download.sh
bash datasets/eia_petroleum_barrel_prices/build.sh
bash datasets/eia_petroleum_barrel_prices/verify.sh
```
