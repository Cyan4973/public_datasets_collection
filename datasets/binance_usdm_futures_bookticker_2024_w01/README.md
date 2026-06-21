# Binance USD-M Futures BookTicker 2024 Week 01

Bounded Binance public-data archive recipe for USD-M futures top-of-book updates.
Each natural **sample** is one symbol-day's ordered sequence of a single best
bid/ask field; each **family** (series) is one field across the symbol-days.

## Homogeneity (why only BTC + ETH)

A family must be **one coherent compression regime**. Best bid/ask **price** and
**quantity** are tick-/lot-lattice quantities whose structure is scale-dependent,
so mixing symbols of different price scales (e.g. BTC ~$42k / 0.1 tick with
DOGE ~$0.09 / 1e-5 tick) destroys the family's coherence even though it raises the
sample count. This recipe therefore keeps **BTCUSDT + ETHUSDT only** — the same
high-value regime used by the accepted `binance_aggtrades_price_f64` family. Do
**not** add other-scale symbols to inflate sample count.

## Structure

- **4 families** (series): `best_bid_price`, `best_bid_qty`, `best_ask_price`, `best_ask_qty` (all float64).
- **Samples per family**: one per symbol-day = 2 symbols × 3 days = **6** (≥5 natural samples).
- **A sample** = a flat little-endian float64 array of that field across the
  earliest `max_rows_per_resource` (2,000,000) top-of-book updates by event time
  for one symbol on one day — large enough (>1M) for the selector to shard
  further. (Some daily ZIPs are not natively time-ordered — rows interleave two
  time streams — so the build selects the earliest-by-time window rather than
  trusting native row order.)
- **Layout**: `samples/<dataset>/<field>/<SYMBOL>_<DATE>_<field>_float64_n<count>.bin`.

## Scope

- market: USD-M futures (`futures/um`)
- symbols: **BTCUSDT, ETHUSDT** (one homogeneous high-value price regime)
- dates: `2024-01-01` .. `2024-01-03`
- per-sample window: earliest 2,000,000 updates by event time

Each daily ZIP is downloaded in full (Binance only serves whole days), so the
download is ~0.65 GB even though only the first window of each file is kept.

## Run

```bash
bash datasets/binance_usdm_futures_bookticker_2024_w01/download.sh
bash datasets/binance_usdm_futures_bookticker_2024_w01/build.sh
bash datasets/binance_usdm_futures_bookticker_2024_w01/verify.sh
```

Tuning: edit `config.json` (`symbols` — keep one price regime, `start_date`/`end_date`, `max_rows_per_resource`). Logs under `${DATA_DIR:-.data}/logs/binance_usdm_futures_bookticker_2024_w01/`.
