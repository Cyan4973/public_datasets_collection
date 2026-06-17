# Binance Archive Material Report

Validated on 2026-06-16 after the user downloaded the selected Binance public
archive ZIPs under `.data/downloads/`.

All four recipes use official `https://data.binance.vision/` historical market
data. Natural sample boundaries are one symbol-period-field sequence: one
symbol-month-field for one-minute klines, and one symbol-day-field for aggregate
trades. Auxiliary IDs, timestamps, and flags are emitted for alignment but do
not count toward acceptance.

| dataset_id | material | scope | resources | source ZIP bytes | primary samples | primary values | primary bytes | primary value count min/median/max | status |
|---|---|---|---:|---:|---:|---:|---:|---:|---|
| `binance_spot_1m_klines_2024_q1` | spot one-minute OHLCV klines | 12 liquid USDT pairs, 2024-01 through 2024-03 | 36 | 63,407,381 | 324 | 14,152,320 | 106,928,640 | 41,760 / 44,640 / 44,640 | ok |
| `binance_usdm_futures_1m_klines_2024_q1` | USD-M futures one-minute OHLCV klines | 10 liquid USDT contracts, 2024-01 through 2024-03 | 30 | 50,839,383 | 270 | 11,793,600 | 89,107,200 | 41,760 / 44,640 / 44,640 | ok |
| `binance_spot_aggtrades_btc_eth_2024_w01` | spot aggregate trades | BTCUSDT and ETHUSDT, 2024-01-01 through 2024-01-07 | 14 | 187,753,108 | 28 | 26,957,784 | 215,662,272 | 353,251 / 821,957 / 2,071,461 | ok |
| `binance_usdm_futures_aggtrades_btc_eth_2024_w01` | USD-M futures aggregate trades | BTCUSDT and ETHUSDT, 2024-01-01 through 2024-01-07 | 14 | 202,982,327 | 28 | 30,405,852 | 243,246,816 | 463,908 / 882,679 / 2,295,158 | ok |

## Validation

- Current promoted `download.sh` scripts were rerun against cached local ZIPs and
  passed semantic validation without network fetches.
- Current promoted `verify.sh` scripts passed for all four recipes.
- `tools/audit_acceptance.py` classifies all four recipes as `ok`.
- Full per-series sample counts, byte distributions, roles, and missing-file
  checks are in `reports/binance_archive_datasets_state.md`.

## Caveats

- The two kline recipes have regular monthly sample sizes because calendar
  months have fixed minute counts. The natural boundary is still respected:
  samples are not concatenated across symbols, months, or fields.
- The two aggregate-trade recipes have much less regular sample sizes because
  trade activity varies by symbol and day.
- The pre-existing `binance_ticker_24hr` recipe remains a thin snapshot and is
  materially weaker than these archive recipes.
