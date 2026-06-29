# CoinPaprika Tickers

Pinned CoinPaprika tickers snapshot with USD quote metrics.

Pinned source: `https://api.coinpaprika.com/v1/tickers`

Selected series:
- `coinpaprika_rank`
- `coinpaprika_price_usd`
- `coinpaprika_market_cap_usd`
- `coinpaprika_volume_24h_usd`
- `coinpaprika_volume_24h_change_pct_f64`
- `coinpaprika_market_cap_change_24h_pct_f64`
- `coinpaprika_percent_change_7d_f64`
- `coinpaprika_ath_price_usd_f64`

Missing-value policy: Filters out tickers missing USD quote blocks.
