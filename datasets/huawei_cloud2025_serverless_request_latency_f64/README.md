# Huawei Public Cloud Trace 2025: serverless per-request latencies (R5, day 30), float64

Per-request service times from Huawei's production YuanRong serverless
platform, released by the Systems Infrastructure Research (SIR) lab in
Edinburgh (Huawei Research UK). Four latency components are emitted as
separate little-endian float64 series, one sample per deployed function.

## Source

- Release README (schema, links):
  <https://github.com/sir-lab/data-release/blob/main/README_data_release_2025.md>
  (repository HEAD `84a9d7727aefed486ea69e022b5ed2476d588700` when probed on
  2026-10-09)
- Resource: the "Region 5 requests" Google Drive object
  `102AFIHkEQHuvG8-hZeWHVFqXeeI-a8xS`, fetched anonymously from
  `https://drive.usercontent.google.com/download?id=...&export=download&confirm=t`
  (attachment `R5.zip`, 269,637,125 bytes, Drive last-modified
  2025-11-20). It contains 200 Spark CSV parts (Deflate, 730,289,350 bytes
  uncompressed). Each part is a consecutive time slice of day 30, with rows in
  `time_worker` order.
- Columns: `time_worker, time_frontend, requestID, clusterName, funcName,
  podID, userID, totalCost_worker, workerCost, runtimeCost,
  totalCost_frontend, frontendCost, busCost, readBodyCost, writeRspCost,
  cpu_usage, memory_usage, requestBodySize`.

## License and attribution

The `sir-lab/data-release` README states: "Licensed under the Creative Commons
Attribution 4.0 International (CC BY 4.0) license." It covers the 2025 Huawei
traces linked from `README_data_release_2025.md`. Attribute the SIR Lab
(Huawei Research UK, Edinburgh) and Huawei's YuanRong serverless platform team,
and cite:

> A. Joosen, A. Hassan, M. Asenov, R. Singh, L. Darlow, J. Wang, Q. Deng,
> A. Barker. *Serverless Cold Starts and Where to Find Them.* EuroSys 2025.
> doi:10.1145/3689031.3696073, arXiv:2410.06145.

## What is collected

| series | source column | meaning (seconds) |
|---|---|---|
| `total_cost_frontend_f64` | `totalCost_frontend` | end-to-end time measured by the frontend |
| `total_cost_worker_f64` | `totalCost_worker` | time in the function worker pod |
| `runtime_cost_f64` | `runtimeCost` | time in the language runtime |
| `bus_cost_f64` | `busCost` | time in the busProxy forwarding component |

- **Sample = one deployed function**, keyed by (`funcName`, `userID`, pool),
  where pool is `podID` without its trailing `-<digits>` pod counter (for
  example `pool22-300-128`). Upstream defines a unique function the same way
  (funcName + userID + poolName). Each sample holds that function's full day-30
  request sequence, stable-sorted by `time_frontend`, so ties keep source order.
  Functions are never concatenated.
- Only functions with at least 1,000 retained requests are emitted. The
  realized function count and per-reason drop counts are written to
  `$DATA_DIR/filtered/<id>/build_stats.json`.
- **Conversion:** each cell is Java double text (`9.31E-4`, `0.023749`) with
  microsecond resolution. It is parsed with Python `float()`, the correctly
  rounded binary64 value, and stored unchanged: no rounding, rescaling or
  integer microseconds.
- **Missing-value policy (build and verify):** a row is dropped from all four
  series when `time_frontend` is blank or non-finite (worker-only rows without
  a frontend join, seen near the end of the day), when the key fields are
  invalid, or when any of the four latencies is blank, NaN/Inf or negative.
  Zero is kept, since `runtimeCost` legitimately reaches 0.0. Unparseable
  non-blank tokens and malformed rows are fatal.

Excluded from the primary payload: `workerCost`, `frontendCost`,
`readBodyCost` and `writeRspCost` (low-precision components; `writeRspCost`
has about 21 distinct values per part), `cpu_usage`, `memory_usage`,
`requestBodySize`, IDs and timestamps.

## Realized scope (build of 2026-10-09)

- 3,448,259 data rows. 5,180 worker-only rows have no `time_frontend` and are
  dropped; no other drops occur (no blank, NaN/Inf or negative latencies).
- 491 functions in total. 37 have at least 1,000 requests; together they hold
  3,415,799 requests (99.2% of kept rows).
- Samples: 37 each for `total_cost_frontend_f64`, `total_cost_worker_f64` and
  `bus_cost_f64`, and 36 for `runtime_cost_f64`. That is 147 files and
  108,981,080 bytes (13,622,635 float64 values).
- Constant-sample rule: a (function, series) sample whose values are all
  identical is skipped for that series only and listed in
  `build_stats.json`. `verify.sh` re-derives this list. In this build,
  function `f49_u128_pool22-300-128` (40,561 requests) logs `runtimeCost = 0.0`
  on every request, so its runtime is presumably not instrumented. Its other
  three series are genuine.
- Request counts per function: min 1,014, median 1,648, max 2,823,735. The
  largest function (`f296_u224_pool22-300-128`) holds 82.7% of all values.
  14 functions have 1,433 to 1,440 requests, consistent with once-a-minute
  timer triggers.

## Homogeneity and caveats

- One platform, one region (R5), one day, one unit (seconds, microsecond
  lattice). R1 (top-100-pods-per-function selection) and R3 (subsample) are
  different sampling regimes and are not used.
- `runtimeCost` is close to `totalCost_worker - workerCost`. In probed parts
  about 75% of rows match exactly and the rest differ by at most 6 µs. The
  series are therefore correlated, but each is logged separately by the
  platform.
- Sample sizes are very skewed. One function (funcName 296, userID 224, pool
  `pool22-300-128`) makes up about 80% of all rows in probed parts. It is one
  natural record and is not sharded.
- Width: the values are microsecond-resolution decimals, so they could in
  principle be represented as integer microseconds. The source representation
  is a floating-point seconds value, and that is what is stored.
- Google Drive hosting has no published checksum. `download.sh` pins the byte
  size and the SHA-256 of the zip central directory, which fixes all 200 member
  names, sizes and CRC-32s. It rejects HTML interstitials (first byte and
  content type are checked before the transfer, and the zip magic and EOCD
  after it), CRC-checks every member, and checks the whole-file SHA-256
  (`5825f744…316e60d`, pinned from the first fetch on 2026-10-09).

## Scripts

- `download.sh`: resumable curl fetch (`-C -`, stall-based abort) and
  `scripts/validate_zip.py`.
- `build.sh`: `scripts/build_samples.py`. Writes samples under
  `$DATA_DIR/samples/<id>/<series>/f<func>_u<user>_<pool>.bin` and the
  index `$DATA_DIR/index/<id>/samples.jsonl`.
- `verify.sh`: `scripts/verify_samples.py`. Re-derives every sample from the
  zip with an independent parser and checks byte-exact hashes, the policy,
  degeneracy, duplicates and the manifest totals.
