# Azure Public Dataset V2 (2019) VM CPU utilization float64 development

## Outcome

Accepted `azure_vm2019_cpu_utilization_readings_f64`. It takes the first 88 complete 5-minute fleet snapshots of the Microsoft Azure 2019 VM trace (AzurePublicDataset V2) and emits per-VM minimum, maximum and average CPU utilization as three native float64 series.

This is a new modality for the corpus: cloud VM workload utilization telemetry. Nothing comparable exists locally, in the registry, in the pipeline ledger or downstream at any width.

## Source and rights

- Source: GitHub release `dataset-v2` of `Azure/AzurePublicDataset`. The legacy Azure Blob URLs redirect there.
- V2 trace: 30 days, one region, 2,695,548 VMs and 1,942,780,023 readings. They form one timestamp-sorted row stream cut into 195 gzip CSVs of 10,000,000 rows each (166,566,456,024 bytes).
- Pinned payloads:
  - file 1: 856,259,637 B, sha256 `010c375e…7032a`
  - file 2: 856,805,928 B, sha256 `26d03dee…43389`
  - file 3 head range: bytes 0–65535, sha256 `93b3b6f5…82291`
  - `schema.csv`: sha256 `638f5ed7…6c518`
- License: CC BY 4.0.
  - The repository root `LICENSE` is the CC BY 4.0 legal code; the GitHub license API reports spdx `CC-BY-4.0`. Code is separately MIT (`LICENSE-CODE`).
  - The trace files are release assets of that repository.
  - The repository's `AzureVMNoiseDataset2024.md` states that the data is licensed CC-BY under that `LICENSE`.
  - The V2 page itself has no license line, so the grant relied on is the repository-level one.
  - `download.sh` re-checks the `LICENSE` text on every run.
- Citation: SOSP'17 Resource Central, as the repository README requests.
- The encrypted VM id is dropped. No personal data.

## Shape and conversion

**Natural record.** One natural record is one 5-minute fleet snapshot: every VM reading that shares one timestamp. A per-VM series is not bounded here, because it would span all 195 files.

**Row stream across files.** Files 1 and 2 are read as one row stream.
- Snapshot t = 13,200 straddles the row-count file cut (18,322 + 207,895 = 226,217 rows) and is joined in stream order.
- The trailing t = 26,400 rows of file 2 (109,061) are dropped as incomplete. The pinned file-3 head starts at t = 26,400.

**Conversion.** Values are `float(token)` of the CSV DOUBLE columns, which are printed at full precision, written as raw little-endian float64 in source row order. The timestamp is kept in the index and the file name only.

**Missing values.** Empty, non-numeric, non-finite or out-of-[0,100] values are fatal, as are malformed rows, timestamp gaps or repeats, duplicate VM ids and constant samples. Build and verify apply the same policy, and nothing is imputed.

## Accepted output

| | |
| --- | --- |
| Series | `vm_cpu_min_pct_f64`, `vm_cpu_max_pct_f64`, `vm_cpu_avg_pct_f64` (fields 3/4/5) |
| Samples | 264 (88 per series), timestamps 0..26,100 s on a 300 s grid |
| Primary values | 59,672,817 (19,890,939 per series) |
| Primary bytes | 477,382,536 (159,127,512 per series) |
| Sample size | 223,522–227,744 values (median 226,171.5) |
| Row accounting | 20,000,000 read = 19,890,939 emitted + 109,061 dropped |
| Value ranges | min 0..99.538 (2,277 zeros); max 0..100.0 (4 zeros); avg 0..99.593 (4 zeros) |
| Distinct values | at least 223,497 in every sample |
| min<=avg<=max violations | 0 |
| Download | 1,713,520,014 B (two full files, the head range, schema, LICENSE and release JSON) |

## Judge checks

- **Gate.** `gate.py` passed with no warnings: 264 samples, 59,672,817 values, 477,382,536 B, median 226,171.5, width 64.
- **verify.sh.** I re-ran it and it exited 0. All 264 samples are byte-identical to an independent zlib/bytes/struct re-derivation. Index statistics, stats counters, row accounting and manifest totals all check out.
- **build.sh.** It reads only local sha-checked files and makes no network calls. The download log shows sha-verified cache hits, release-API validation (195 assets) and an HTTP 206 Content-Range for the file-3 head.
- **Width honesty.**
  - Avg/max values never round-trip through float32; for min, only the exact zeros do.
  - The low 16 mantissa bits take 62.3k–62.8k distinct patterns per sample out of 65,536, so they are not quantized.
  - Source tokens are mostly 17 significant digits, and all 2.1M tokens checked round-trip.
- **Homogeneity.** Per-sample means are stable across all 88 snapshots (avg 9.27–10.15 %). Medians are about 5 % (avg), a skewed real fleet distribution. All 264 sha256 values are unique.
- **Near-duplicates.**
  - Consecutive snapshots share 99.8 % of their VMs, with per-VM avg correlation 0.94 from t0 to t300.
  - The median relative change is 11 % and there are 0 exact value repeats, so the snapshots are not near-duplicates.
  - The lag-1 correlation between adjacent rows within a sample is 0.004.
- **Correction to the README on row order.** The publisher's order is not globally reshuffled.
  - Shared VMs keep a global position correlation of 0.9999998 between t0 and t300.
  - Each VM drifts within about ±200 positions.
  - Locally the order is random: 52.7 % of consecutive pairs keep their order (random is 50 %) and only 3.7 % of neighbours stay adjacent.
  - The README's conclusions still hold: samples are not shifted copies of each other, and adjacency within a sample carries no structure.
- **Rights.** I checked the license API, the `LICENSE` and `LICENSE-CODE` heads, the repo README (release hosting, citation request) and the `AzureVMNoiseDataset2024.md` license statement. No credentials appear in any script.
- **Novelty.** `novelty.py` with terms azure, vm cpu, cpu utilization, cpu readings, cluster trace, borg, alibaba, utilization and telemetry found no compute-telemetry family in datasets, staging, registry, ledger or downstream.
- **Known limits.**
  - Coverage is only the first 7.3 h of a 30-day trace, with relative timestamps.
  - It is one VM population, so diversity is narrower than snapshots spread across the trace would give.
  - Each sample still holds about 226k distinct VMs at high entropy.
