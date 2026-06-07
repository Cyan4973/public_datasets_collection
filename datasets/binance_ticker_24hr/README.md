# Binance 24h Ticker Snapshot

Pinned Binance 24-hour ticker snapshot across trading pairs.

Pinned source: `https://api.binance.com/api/v3/ticker/24hr`

Selected series:
- `binance_price_change_pct`
- `binance_weighted_avg_price`
- `binance_last_price`
- `binance_quote_volume`
- `binance_count`
- `binance_open_time_ms`

Missing-value policy: Filters out tickers missing numeric quote fields.
