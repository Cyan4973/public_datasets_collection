# Binance USD-M Futures Aggregate Trades BTC/ETH 2024 Week 01

Bounded Binance public-data archive recipe for USD-M futures aggregate trade
rows.

Scope:

- market: USD-M futures
- symbols: `BTCUSDT`, `ETHUSDT`
- dates: `2024-01-01` through `2024-01-07`
- resources: `14` daily ZIP files from `https://data.binance.vision/`
- natural sample boundary: one symbol-day-field sequence

Run:

```bash
datasets/binance_usdm_futures_aggtrades_btc_eth_2024_w01/download.sh
datasets/binance_usdm_futures_aggtrades_btc_eth_2024_w01/build.sh
datasets/binance_usdm_futures_aggtrades_btc_eth_2024_w01/verify.sh
```

Primary fields are trade price and quantity. Aggregate trade ids, first/last
trade ids, timestamps, and buyer-maker flags are auxiliary and do not count
toward acceptance.

Validated local output:

- source ZIP bytes: `202,982,327`
- primary samples: `28`
- primary values: `30,405,852`
- primary bytes: `243,246,816`
- primary sample value range: `463,908` to `2,295,158`, median `882,679`
