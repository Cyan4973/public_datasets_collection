# FRED Consumer Sentiment Monthly

This recipe collects the FRED `UMCSENT` series and emits one sample per year.

Selected scope:
- FRED series: `UMCSENT`
- years `2015` through `2024`
- one output sample per year per series

Series emitted by `build.sh`:
- `fred_value_f32` (`float32`, little-endian)

Notes:
- Source data comes from the FRED graph CSV endpoint.
- `download.sh` validates the exact `DATE,UMCSENT` header.
- Missing-value policy: blank values, `.` values, blank dates, malformed dates,
  and malformed numeric values are filtered.

Usage:

```sh
bash datasets/fred_consumer_sentiment_monthly/download.sh
bash datasets/fred_consumer_sentiment_monthly/build.sh
bash datasets/fred_consumer_sentiment_monthly/verify.sh
```
