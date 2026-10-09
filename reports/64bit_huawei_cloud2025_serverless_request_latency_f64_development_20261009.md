# Huawei Cloud 2025 serverless per-request latency float64 development

## Outcome

Accepted `huawei_cloud2025_serverless_request_latency_f64`. It holds per-request service times from Huawei's production YuanRong serverless platform, from the CC BY 4.0 Huawei Public Cloud Trace 2025 released by the SIR Lab (Huawei Research UK, Edinburgh).

This is the corpus's first family of request service latencies. The nearest existing material is different:
- `zenodo_starlink_irtt_rtt_i32`: network probe round-trip time, 32-bit.
- `uci_sgemm_gpu_runtimes_f32`: GPU kernel benchmark runtimes.
- `azure_vm2019_cpu_utilization_readings_f64` and `google_clusterdata2011_task_usage_f32`: resource utilization, not latency.

Measured breadth (zlsim) is OK for all four series:

| Series | Nearest distance | Nearest family |
|---|---|---|
| totalCost_frontend | 0.085 | NASA POWER clear-sky shortwave |
| totalCost_worker | 0.069 | NASA POWER humidity |
| runtimeCost | 0.072 | UCI wine density |
| busCost | 0.088 | NASA POWER humidity |

## Source and rights

- Source: the "Region 5 requests" object of sir-lab/data-release, linked from `README_data_release_2025.md`.
  - Google Drive id `102AFIHkEQHuvG8-hZeWHVFqXeeI-a8xS`, fetched anonymously from drive.usercontent.google.com with `confirm=t`.
  - Attachment `R5.zip`, Drive last-modified 2025-11-20.
- Bytes: 269,637,125, containing 200 Spark CSV parts (730,289,350 bytes uncompressed, 3,448,259 data rows).
- SHA-256: `5825f74443cf6e4f5df264f8c94d439fc9eae576399f9786a50ca4cb3316e60d`
- Central-directory SHA-256: `68bd434f9a9f812826658c8b9c3150833e8871eb1cc8a7560d16bea0d9ca6a8b`. This pins all 200 member names, sizes and CRC-32s.
- License: CC BY 4.0. The repository README (HEAD `84a9d7727aefed486ea69e022b5ed2476d588700`) describes the public Huawei Cloud FaaS trace releases and states "Licensed under the Creative Commons Attribution 4.0 International (CC BY 4.0) license."
- Attribution: SIR Lab and Huawei YuanRong; cite Joosen et al., *Serverless Cold Starts and Where to Find Them*, EuroSys 2025, doi:10.1145/3689031.3696073.
- Google Drive publishes no checksum, so the pins come from the first fetch on 2026-10-09.

## Shape and conversion

- **Natural record:** one deployed function's complete day-30 request sequence.
  - Function key: (funcName, userID, podID pool prefix), which is upstream's funcID definition.
  - Order: stable-sorted by `time_frontend`.
  - Functions are never concatenated or sharded.
- **Primary series** (one per latency column; all seconds on a 1 µs lattice):
  - `totalCost_frontend`: end-to-end time measured by the frontend.
  - `totalCost_worker`: time in the worker pod.
  - `runtimeCost`: time in the language runtime.
  - `busCost`: time in the busProxy.
- **Conversion:** each Java double cell (for example `1.24E-4`, `0.022946`) is parsed with `float()` and stored unchanged as little-endian float64. There is no rounding, rescaling or integer remap.
- **Missing-value policy, applied in build and verify:**
  - A row is dropped from all four series if `time_frontend` is blank, the key is invalid, or any latency is blank, non-finite or negative. Zero is kept.
  - A constant (function, series) sample is skipped for that series only and listed in `build_stats.json`.
- **Excluded:** workerCost, frontendCost, readBodyCost and writeRspCost (low precision), cpu/memory usage, body size, IDs and timestamps.
- **Regions:** R1 (top 100 pods per function) and R3 (a subsample) are different sampling regimes and are excluded. R2 and R4 are full regions but are 24 GB and 5.3 GB of zips, so they are out of bounds. One complete region-day is the bounded subset.

## Accepted output

- Data rows: 3,448,259. Kept: 3,443,079. Dropped: 5,180, all worker-only rows without `time_frontend`; nothing was blank, non-finite or negative.
- Functions: 491 in total; 37 have at least 1,000 requests and hold 3,415,799 rows (99.2%).
- Samples per series: `total_cost_frontend_f64` 37, `total_cost_worker_f64` 37, `runtime_cost_f64` 36, `bus_cost_f64` 37. f49_u128_pool22-300-128 logs runtimeCost = 0.0 on all 40,561 requests and is skipped for that series only.
- Values per series:
  - 3,415,799 values (27,326,392 bytes) each for frontend, worker and bus.
  - 3,375,238 values (27,001,904 bytes) for runtime.
- Primary total: 147 samples, 13,622,635 values, 108,981,080 bytes.
- Sample size: minimum 1,014 values, median 1,648, maximum 2,823,735.
- Skew: f296_u224_pool22-300-128 holds 82.9% of all values. It is one natural record.
- Index aggregate SHA-256 over sorted `path sha256` lines: `3748e1b5f0e767f8002c5c63ae092c84e38ceab39f4e7ef6de33bd02712571b8`

## Judge checks

- **Mechanics:** `gate.py staging/<id>` passed with no warnings.
- **Verify:** I ran `bash verify.sh` myself and it printed `verify: OK`.
  - It re-derived 147 samples byte-exact from the zip with an independent split-based parser.
  - It matched the drop counts, the constant-skip list and the manifest totals.
- **Download:** the driver's download log shows size, central-directory SHA-256 and whole-file SHA-256 all matching, and every member CRC passing. `build.sh` reads only the local zip.
- **Bytes** (struct decode of f296, f142, f322, f534 and f49 across all series):
  - Every value is on the 1 µs lattice. Ranges are plausible, from about 0.24 ms bus hops to 81 s long calls.
  - There is no fill value. Distinct counts are high (142,639 for f296 frontend).
  - The first stored f296 values match the raw CSV text and the time_frontend reordering.
  - frontend ≥ worker + bus holds on 100% of rows in all 37 functions.
- **Width:** the source column is a Java double ('E-4' notation). 8-significant-digit values do not fit exactly in float32, and integer microseconds would be a local remap, so float64 is the honest width.
- **Redundancy:**
  - H(runtime | worker) is about 6.2 bits per value against H(runtime) 14.7 bits in f296. runtimeCost is correlated with worker time but not determined by it (it is about worker − workerCost, and workerCost is not emitted), and it is a separately documented upstream field.
  - H(frontend | worker, bus) is about 10.4 of 15.7 bits.
  - Keeping all four series is consistent with the corpus's multi-column telemetry families.
- **Rights:** I fetched raw README.md and README_data_release_2025.md at HEAD 84a9d77. The CC BY 4.0 statement is present, and the request-table section links the exact Drive object. There are no credentials in any script and no personal data in the payload.
- **Novelty:**
  - `novelty.py` URL and term checks hit only this staging recipe, plus an incidental 'huawei' in hutubs.
  - `--type request_latency_telemetry`, the instrument line and the archive all return 0.
  - Comparable types (network_packet_latency, kernel_runtime_benchmark, vm_telemetry) are different quantities. Labeled new_quantity.
- **Scope:** 1-byte range probes show R4 parts are 2,698,407,304 and 2,653,067,939 bytes and R2 parts about 2.4 GB each. R5 is therefore the only full-region table that fits under the cap.
