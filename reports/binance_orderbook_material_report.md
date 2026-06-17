# Binance Order-Book Material Report

Validated on 2026-06-16 after the user downloaded the selected Binance public
archive ZIPs under `.data/downloads/`.

These recipes add order-book shapes that differ from the previously accepted
Binance kline and aggregate-trade datasets.

| dataset_id | material | scope | resources | source ZIP bytes | primary samples | primary values | primary bytes | primary value count min/median/max | status |
|---|---|---|---:|---:|---:|---:|---:|---:|---|
| `binance_usdm_futures_bookticker_btc_eth_2024_w01` | USD-M futures top-of-book updates | BTCUSDT and ETHUSDT, first two hours of 2024-01-01 | 2 | 218,537,086 | 8 | 7,355,408 | 58,843,264 | 690,547 / 919,426 / 1,148,305 | ok |
| `binance_usdm_futures_bookdepth_btc_eth_2024_w01` | USD-M futures order-book depth grids | BTCUSDT and ETHUSDT, 2024-01-01 through 2024-01-07 | 14 | 6,761,986 | 28 | 806,360 | 6,450,880 | 28,790 / 28,800 / 28,800 | ok |

## Shape Notes

- `bookTicker` samples are one-dimensional event-window sequences of best bid
  price, best bid quantity, best ask price, and best ask quantity. The full
  source day is very dense, so the recipe uses a fixed first-two-hour window
  rather than materializing the entire day.
- `bookDepth` samples are timestamp-by-percentage grids. Primary series are
  `depth` and `notional`; `timestamp_ms` and `percentage` are auxiliary
  coordinates and do not count toward acceptance.

## Validation

- Current promoted `verify.sh` scripts passed for both recipes.
- `tools/audit_acceptance.py` classifies both recipes as `ok`.
- Full per-series sample counts, byte distributions, roles, and missing-file
  checks are in `reports/binance_orderbook_state.md`.

## Caveats

- `bookTicker` requires downloading two large daily archives to emit a bounded
  two-hour primary window. This is still within repository size rules, but it is
  operationally heavier than the final primary output.
- `bookDepth` has regular sample sizes because the source is a fixed-cadence
  percentage-level grid. The grid shape is documented in the sample index so the
  trainer selector can recognize it as 2D material.
