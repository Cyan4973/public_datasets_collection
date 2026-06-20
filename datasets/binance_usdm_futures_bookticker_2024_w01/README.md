# Binance USD-M Futures BookTicker 2024 Week 01

Bounded Binance public-data archive recipe for USD-M futures top-of-book updates.
Each natural **sample** is one symbol-day's ordered sequence of a single best
bid/ask field; each **family** (series) is one field across all symbol-days.
(Supersedes the BTC/ETH-only `binance_usdm_futures_bookticker_btc_eth_2024_w01`.)

## Structure

- **4 families** (series): `best_bid_price`, `best_bid_qty`, `best_ask_price`, `best_ask_qty` (all float64).
- **Samples per family**: one per symbol-day = up to 20 symbols x 3 days = **~60**.
- **A sample** = a flat little-endian float64 array of that field across the
  earliest `max_rows_per_resource` (250000) top-of-book updates by event time for
  one symbol on one day. (Some daily ZIPs are not natively time-ordered — the
  rows interleave two time streams — so the build selects the earliest-by-time
  window rather than trusting native row order.)
- **Layout**: `samples/<dataset>/<field>/<SYMBOL>_<DATE>_<field>_float64_n<count>.bin`.

## Scope

- market: USD-M futures (`futures/um`)
- symbols (20): BTC, ETH, BNB, SOL, XRP, ADA, DOGE, AVAX, LINK, DOT, LTC, TRX, BCH, ETC, ATOM, MATIC, NEAR, FIL, APT, ARB (all USDT perpetuals)
- dates: `2024-01-01` .. `2024-01-03`
- per-sample cap: earliest 250,000 updates by event time
- missing symbol-days are skipped (`skip_missing_resources`)

Each daily ZIP is downloaded in full (Binance only serves whole days), so the
download is several GB even though only the first window of each file is kept.
`download.sh` raises `MAX_SOURCE_BYTES` accordingly.

## Run

```bash
bash datasets/binance_usdm_futures_bookticker_2024_w01/download.sh
bash datasets/binance_usdm_futures_bookticker_2024_w01/build.sh
bash datasets/binance_usdm_futures_bookticker_2024_w01/verify.sh
```

Tuning: edit `config.json` (`symbols`, `start_date`/`end_date`, `max_rows_per_resource`, `max_time_span_seconds`). Logs under `${DATA_DIR:-.data}/logs/binance_usdm_futures_bookticker_2024_w01/`.
