# Binance USD-M Futures BookTicker BTC/ETH 2024 Week 01

Bounded Binance public-data archive recipe for USD-M futures top-of-book
updates. This is intentionally a different shape from klines and aggregate
trades: each natural sample is a symbol-day-field event sequence of best bid
and best ask prices and quantities.

Scope:

- market: USD-M futures
- symbols: `BTCUSDT`, `ETHUSDT`
- dates: `2024-01-01`
- resources: `2` daily ZIP files from `https://data.binance.vision/`
- bounded subset: first two hours of updates from each symbol-day file
- natural sample boundary: one symbol-day-field event-window sequence

Run:

```bash
bash datasets/binance_usdm_futures_bookticker_btc_eth_2024_w01/download.sh
bash datasets/binance_usdm_futures_bookticker_btc_eth_2024_w01/build.sh
bash datasets/binance_usdm_futures_bookticker_btc_eth_2024_w01/verify.sh
```

Primary fields are best bid/ask prices and quantities. The source files are
very dense, so this staged recipe intentionally keeps contiguous ordered
time windows from each symbol-day file rather than materializing the entire day.

Validated local output:

- source ZIP bytes: `218,537,086`
- primary samples: `8`
- primary values: `7,355,408`
- primary bytes: `58,843,264`
- primary sample value range: `690,547` to `1,148,305`, median `919,426`
