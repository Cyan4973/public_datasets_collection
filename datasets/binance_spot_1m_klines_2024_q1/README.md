# Binance Spot 1m Klines 2024 Q1

Bounded Binance public-data archive recipe for spot-market one-minute OHLCV
kline rows.

Scope:

- market: spot
- symbols: `BTCUSDT`, `ETHUSDT`, `BNBUSDT`, `SOLUSDT`, `XRPUSDT`,
  `ADAUSDT`, `DOGEUSDT`, `LINKUSDT`, `LTCUSDT`, `AVAXUSDT`, `TRXUSDT`,
  `DOTUSDT`
- months: `2024-01` through `2024-03`
- resources: `36` monthly ZIP files from `https://data.binance.vision/`
- natural sample boundary: one symbol-month-field sequence

Run:

```bash
datasets/binance_spot_1m_klines_2024_q1/download.sh
datasets/binance_spot_1m_klines_2024_q1/build.sh
datasets/binance_spot_1m_klines_2024_q1/verify.sh
```

Primary fields are open/high/low/close price, base volume, quote volume, trade
count, taker-buy base volume, and taker-buy quote volume. Open/close timestamps
are auxiliary.

Validated local output:

- source ZIP bytes: `63,407,381`
- primary samples: `324`
- primary values: `14,152,320`
- primary bytes: `106,928,640`
- primary sample value range: `41,760` to `44,640`, median `44,640`
