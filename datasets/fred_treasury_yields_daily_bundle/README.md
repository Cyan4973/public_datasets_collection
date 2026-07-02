# FRED Daily Treasury Yields Bundle

`fred_treasury_yields_daily_bundle` emits daily U.S. Treasury constant-maturity
yield observations from FRED as a homogeneous `float32` family.

The natural record is one FRED Treasury maturity series. The build keeps only
native numeric percent-yield observations and writes one raw little-endian
`float32` array per maturity.

```sh
bash datasets/fred_treasury_yields_daily_bundle/download.sh
bash datasets/fred_treasury_yields_daily_bundle/build.sh
bash datasets/fred_treasury_yields_daily_bundle/verify.sh
```

The default downloader covers fixed FRED series IDs from `1962-01-02` through
`2024-12-31`. The verifier requires a materially larger bundle than the old
single-series 2015-2024 recipes.
