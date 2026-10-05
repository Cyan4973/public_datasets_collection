# Rejected: Tardis.dev Binance Futures SOL L2 Book Snapshots

- Date: 2026-09-24
- Candidate: `tardis_binance_futures_sol_book_snapshot_25`
- Intended domain: cryptocurrency limit order book depth ("heatmap")
- Intended representation: 25-level bid/ask price and amount columns sampled
  over time for a single perpetual instrument
- Decision: rejected on licence terms, not on technical or quality grounds

## Origin of the request

The requested sample was described as "21MB of Solana Heatmap Data, ~4 hours at
1s intervals". No published artifact with that title, size, or cadence exists.
The description matches a *derived* order book depth grid: a price-level by
time matrix, which at 14,400 one-second steps by ~100 numeric columns lands
near 21 MB when serialised as CSV text.

## Candidate source

`datasets.tardis.dev` serves a free-sample tier without an API key:

```
https://datasets.tardis.dev/v1/binance-futures/book_snapshot_25/2024/01/01/SOLUSDT.csv.gz
```

Verified characteristics:

| Field | Value |
|---|---|
| HTTP status | 200 (anonymous, no API key) |
| Transfer size | 102,209,248 bytes (gzip) |
| Rows | 1,531,243 |
| Columns | 104 |
| Schema | `exchange,symbol,timestamp,local_timestamp` + `asks[0..24].price/amount` + `bids[0..24].price/amount` |
| Timestamps | microseconds since epoch |
| Cadence | event-driven, ~17 snapshots/second (not fixed 1s) |
| Instrument | SOLUSDT perpetual, `availableSince` 2020-09-14 |

Technically this is strong material: 100 numeric columns per snapshot,
~153 million values for a single day, one instrument on one venue, so
homogeneous. Ranged GETs are rejected by Cloudflare with HTTP 403, so the file
can only be fetched whole.

## Blocking clauses

The Tardis.dev Licence Agreement (`https://docs.tardis.dev/legal/terms-of-service`)
governs the free sample tier explicitly: the licence attaches "By accessing,
downloading or using Data or Services provided by Tardis.dev ... including
sample or trial Data". The sample file is therefore licensed, not public
domain, and three clauses each independently rule it out:

- **Clause 9.2** — the Customer shall not "redistribute or resell the Data ...
  except for reselling or redistributing aggregated and calculated Derived
  Data, including OHLC or OHLCV candles, at a resolution of 10 minutes or
  longer, where no raw Data is exposed and the Data cannot reasonably be
  reconstructed". A one-second depth grid is raw Data at far finer resolution
  than the 10-minute carve-out permits.
- **Clause 9.5** — the Customer shall not use the Data "to pre-train, train,
  fine-tune, distil, validate, evaluate, benchmark or improve any artificial
  intelligence or machine learning model or system", except for internal
  quantitative use, nor distribute any model developed using it. This corpus
  exists to serve as training and benchmark material, which is the prohibited
  use named directly.
- **Permitted Use** is defined as "internal business, research, educational or
  personal use by the Customer and Customer Users only" and expressly excludes
  use for the benefit of any third party. Publishing a recipe that reproduces
  the file for other people is outside that scope.

Schedule 1(d) reinforces this: no extracting, redistributing, copying or
storing the Data for any purpose not expressly permitted.

## Adjacent routes also checked

- **Hyperliquid public archive** (`s3://hyperliquid-archive/market_data/<date>/<hour>/l2Book/SOL.lz4`)
  is the closest structural match to the request — native L2 snapshots in
  per-hour files, so four hours genuinely approaches the stated size. The
  bucket is requester-pays: anonymous GET returns HTTP 403 `AccessDenied`
  ("Anonymous users cannot invoke requests against Requester Pays buckets").
- **Binance public archive** (`data.binance.vision`) carries
  `data/futures/um/daily/bookDepth/SOLUSDT/`, but at one-minute cadence and
  ~400 KB/day compressed — too coarse to form a depth heatmap. The full daily
  category listing (`aggTrades`, `bookDepth`, `bookTicker`,
  `indexPriceKlines`, `klines`, `markPriceKlines`, `metrics`,
  `premiumIndexKlines`, `trades`) confirms Binance publishes no raw L2 diff
  stream; `bookTicker` is top-of-book only and yields no grid.

## Disposition

No payload retained. The probe file was deleted after inspection. Do not retry
this source unless Tardis.dev publishes sample data under terms that permit
redistribution and machine-learning use, or unless an exchange publishes raw
per-level L2 depth for a single instrument under anonymous, redistributable
terms.
