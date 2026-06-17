# Binance USD-M Futures BookDepth BTC/ETH 2024 Week 01

Bounded Binance public-data archive recipe for USD-M futures order-book depth
curves. This is intentionally a different shape from klines and aggregate
trades: when the source rows form a complete timestamp-by-percentage grid, the
sample index records the sample geometry as a 2D grid.

Scope:

- market: USD-M futures
- symbols: `BTCUSDT`, `ETHUSDT`
- dates: `2024-01-01` through `2024-01-07`
- resources: `14` daily ZIP files from `https://data.binance.vision/`
- natural sample boundary: one symbol-day-field sequence or grid

Run:

```bash
bash datasets/binance_usdm_futures_bookdepth_btc_eth_2024_w01/download.sh
bash datasets/binance_usdm_futures_bookdepth_btc_eth_2024_w01/build.sh
bash datasets/binance_usdm_futures_bookdepth_btc_eth_2024_w01/verify.sh
```

Primary fields are depth and notional. Timestamp and percentage-level
coordinates are auxiliary.

Validated local output:

- source ZIP bytes: `6,761,986`
- primary samples: `28`
- primary values: `806,360`
- primary bytes: `6,450,880`
- primary sample value range: `28,790` to `28,800`, median `28,800`
- sample geometry: timestamp-by-percentage grids, typically `2880 x 10`
