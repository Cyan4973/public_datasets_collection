# Huawei Public Cloud Trace 2025 (SIR Lab Edinburgh / YuanRong serverless): Per-Request End-to-End and Component Latencies (totalCost_frontend, totalCost_worker, runtimeCost, busCost), Region 5 Day 30, Float64

- Candidate id: `huawei_cloud2025_serverless_request_latency_f64`
- Width: float64
- Quantity: Per-request service-time measurements in seconds (microsecond resolution) from a production serverless platform. Four primary series: frontend-measured end-to-end latency, time in the function worker pod, time in the language runtime, and time in the busProxy forwarding component.
- Source: https://github.com/sir-lab/data-release/blob/main/README_data_release_2025.md
- Resources: https://drive.usercontent.google.com/download?id=102AFIHkEQHuvG8-hZeWHVFqXeeI-a8xS&export=download&confirm=t
- License: CC BY 4.0
- License evidence: https://github.com/sir-lab/data-release/blob/main/README.md
- License quote: Licensed under the Creative Commons Attribution 4.0 International (CC BY 4.0) license.
- Natural record: One request log row (worker + frontend join). A sample is the time-ordered request series of one function (funcName+userID+pool, i.e. one deployed function), sorted by time_frontend, with one series per latency field. A minimum request count per function (e.g. >=1,000) avoids tiny samples.
- Estimated samples: 150
- Estimated primary values: 13,600,000
- Estimated download bytes: 269,637,125
- Estimated primary bytes: 108,800,000
- Decode path: curl R5.zip (269,637,125 B) from drive.usercontent.google.com with confirm=t; anonymous range GETs work, and the response has content-disposition filename="R5.zip". The zip holds 200 Spark CSV parts (R5/part-000NN-*.csv, Deflate, 730,289,350 B uncompressed). Read them with zipfile and csv.reader, group by (funcName,userID,podID pool prefix), sort by time_frontend, parse the latency columns with float() (they appear in Java double repr such as '9.31E-4' or '0.002367'), and emit '<d' arrays. Pure stdlib.
- Novelty kind: new_modality
- Measurement type: request_latency_telemetry
- Instrument line: Huawei YuanRong serverless platform frontend/worker logs
- Archive collection: sir_lab_huawei_public_cloud_trace_2025
- Novelty evidence: novelty.py --url github.com/sir-lab/data-release gave same-host-only matches (unrelated GitHub-hosted recipes). The terms huawei / serverless / 'cold start' / latency matched no ledger, registry or downstream entries; the only hit was an incidental 'huawei' mention in hutubs_measured_hrir_f64. --type request_latency_telemetry --archive huawei_sir_lab_data_release gave 0/0. Corpus latency material is limited to zenodo_starlink_irtt_rtt_i32 (network RTT at 32 bits). The vm_telemetry entries (Azure VM CPU, Google 2011 task usage) are utilization, not request service times.
- Homogeneity: One platform (Huawei YuanRong), one region (R5), one day (day 30), one unit (seconds, microsecond resolution). Each latency component is its own series, and samples are per-function. Other regions are excluded on purpose: R1 is a top-100-pods-per-function selection and R3 is a subsample, so they are different sampling regimes. Timestamps, IDs, cpu_usage (cores), memory_usage (MB) and requestBodySize are excluded.
- Risks: (1) Hosted on Google Drive, not an institutional archive: no published checksum, so download.sh must pin size and sha256 after the first fetch, and Drive's confirm flow could change. (2) Latencies are integer microseconds printed as decimal seconds, so a judge could argue width-hollowness. The values span about 1e-6 to more than 10 s with thousands of distinct values per few-thousand rows, and the source representation is a float, like the accepted decimal-lattice Binance f64 families. (3) Low-precision components (writeRspCost has 21 distinct values, readBodyCost 390) are deliberately left out; workerCost (264 distinct) is borderline and excluded. (4) The row count of about 3.4M is estimated from compression ratio (2,529 rows per ~200 KB compressed; 730 MB uncompressed total). (5) The data is CC BY per the release README; there is no separate per-file license in the zip.
- Probe evidence: A range GET bytes=0-0 on the Drive usercontent URL returned 206 with content-range '/269637125' and filename R5.zip. A tail range read (64 KB) of the zip EOCD showed 200 entries, central directory at offset 269,616,103, members summing to 730,289,350 B uncompressed. Inflating the first 200 KB gave the header time_worker,time_frontend,requestID,clusterName,funcName,podID,userID,totalCost_worker,workerCost,runtimeCost,totalCost_frontend,frontendCost,busCost,readBodyCost,writeRspCost,cpu_usage,memory_usage,requestBodySize. In 2,527 rows, totalCost_frontend had 2,481 distinct values, totalCost_worker 2,321, runtimeCost 2,298 and busCost 1,879, across 48 functions. All 37 request-table zips (R1-R5) resolve anonymously.

Proposed by the autocollect scout on 2026-10-09 (transcript `.data/pipeline/logs/scout_64bit/scout.20261009_110429.jsonl`).
