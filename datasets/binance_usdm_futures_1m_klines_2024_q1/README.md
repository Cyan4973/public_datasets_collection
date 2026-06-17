# Binance USD-M Futures 1m Klines 2024 Q1

Bounded Binance public-data archive recipe for USD-M futures one-minute OHLCV
kline rows.

Scope:

- market: USD-M futures
- symbols: `BTCUSDT`, `ETHUSDT`, `BNBUSDT`, `SOLUSDT`, `XRPUSDT`,
  `ADAUSDT`, `DOGEUSDT`, `LINKUSDT`, `LTCUSDT`, `AVAXUSDT`
- months: `2024-01` through `2024-03`
- resources: `30` monthly ZIP files from `https://data.binance.vision/`
- natural sample boundary: one symbol-month-field sequence

Run:

```bash
datasets/binance_usdm_futures_1m_klines_2024_q1/download.sh
datasets/binance_usdm_futures_1m_klines_2024_q1/build.sh
datasets/binance_usdm_futures_1m_klines_2024_q1/verify.sh
```

Primary fields are open/high/low/close price, base volume, quote volume, trade
count, taker-buy base volume, and taker-buy quote volume. Open/close timestamps
are auxiliary.

Validated local output:

- source ZIP bytes: `50,839,383`
- primary samples: `270`
- primary values: `11,793,600`
- primary bytes: `89,107,200`
- primary sample value range: `41,760` to `44,640`, median `44,640`
