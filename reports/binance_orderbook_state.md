# Dataset State Report

Acceptance floor used by this report: at least `10000` primary values, at least `102400` primary bytes, median primary sample size at least `1000` values, and primary output at most `1000000000` bytes.

## `binance_usdm_futures_bookdepth_btc_eth_2024_w01`

- status: `ok`
- reasons: `none`
- primary_samples: 28
- primary_values: 806360
- primary_bytes: 6450880
- primary_value_count_range: 28790 / 28800 / 28800 min/median/max
- primary_size_range_bytes: 230320 / 230400 / 230400 min/median/max
- primary_size_distribution_bytes: 230320 / 230320 / 230400 / 230400 / 230400 / 230400 / 230400 min/p10/p25/median/p75/p90/max
- primary_same_size_fraction: 0.857143

| series_id | role | kind | width | samples | values | bytes | value distribution min/p10/p25/median/p75/p90/max | byte distribution min/p10/p25/median/p75/p90/max | same-size fraction | missing files |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `depth` | primary | float | 64 | 14 | 403180 | 3225440 | 28790 / 28793 / 28800 / 28800 / 28800 / 28800 / 28800 | 230320 / 230344 / 230400 / 230400 / 230400 / 230400 / 230400 | 0.857143 | 0 |
| `notional` | primary | float | 64 | 14 | 403180 | 3225440 | 28790 / 28793 / 28800 / 28800 / 28800 / 28800 / 28800 | 230320 / 230344 / 230400 / 230400 / 230400 / 230400 / 230400 | 0.857143 | 0 |
| `percentage` | auxiliary | float | 64 | 14 | 403180 | 3225440 | 28790 / 28793 / 28800 / 28800 / 28800 / 28800 / 28800 | 230320 / 230344 / 230400 / 230400 / 230400 / 230400 / 230400 | 0.857143 | 0 |
| `timestamp_ms` | auxiliary | uint | 64 | 14 | 403180 | 3225440 | 28790 / 28793 / 28800 / 28800 / 28800 / 28800 / 28800 | 230320 / 230344 / 230400 / 230400 / 230400 / 230400 / 230400 | 0.857143 | 0 |

## `binance_usdm_futures_bookticker_btc_eth_2024_w01`

- status: `ok`
- reasons: `none`
- primary_samples: 8
- primary_values: 7355408
- primary_bytes: 58843264
- primary_value_count_range: 690547 / 919426 / 1148305 min/median/max
- primary_size_range_bytes: 5524376 / 7355408 / 9186440 min/median/max
- primary_size_distribution_bytes: 5524376 / 5524376 / 5524376 / 7355408 / 9186440 / 9186440 / 9186440 min/p10/p25/median/p75/p90/max
- primary_same_size_fraction: 0.500000

| series_id | role | kind | width | samples | values | bytes | value distribution min/p10/p25/median/p75/p90/max | byte distribution min/p10/p25/median/p75/p90/max | same-size fraction | missing files |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `best_ask_price` | primary | float | 64 | 2 | 1838852 | 14710816 | 690547 / 736322.8 / 804986.5 / 919426 / 1033865.5 / 1102529.2 / 1148305 | 5524376 / 5890582.4 / 6439892 / 7355408 / 8270924 / 8820233.6 / 9186440 | 0.500000 | 0 |
| `best_ask_qty` | primary | float | 64 | 2 | 1838852 | 14710816 | 690547 / 736322.8 / 804986.5 / 919426 / 1033865.5 / 1102529.2 / 1148305 | 5524376 / 5890582.4 / 6439892 / 7355408 / 8270924 / 8820233.6 / 9186440 | 0.500000 | 0 |
| `best_bid_price` | primary | float | 64 | 2 | 1838852 | 14710816 | 690547 / 736322.8 / 804986.5 / 919426 / 1033865.5 / 1102529.2 / 1148305 | 5524376 / 5890582.4 / 6439892 / 7355408 / 8270924 / 8820233.6 / 9186440 | 0.500000 | 0 |
| `best_bid_qty` | primary | float | 64 | 2 | 1838852 | 14710816 | 690547 / 736322.8 / 804986.5 / 919426 / 1033865.5 / 1102529.2 / 1148305 | 5524376 / 5890582.4 / 6439892 / 7355408 / 8270924 / 8820233.6 / 9186440 | 0.500000 | 0 |
