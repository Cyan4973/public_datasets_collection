# Google Borg clusterdata-2011-2 task-usage CPI/MAI float32 development

## Outcome

Accepted `google_clusterdata2011_task_usage_f32` from the official Google cluster trace `clusterdata-2011-2` (trace version 2.1).

The family holds per-task hardware-counter efficiency measures from Borg's `task_usage` table, one sample per 5-minute cluster measurement window:

- cycles per instruction (CPI)
- memory accesses per instruction (MAI)

The source is new to the corpus. The only nearby material is `azure_vm2019_cpu_utilization_readings_f64`, which comes from a different provider, measures VM CPU percent, and is stored as float64.

The first judge pass asked for one repair (repair 1 of 2). The CPU-rate series (field 6) had to go: all 1,289,426 values checked were a half-precision code widened to float32. A float16-recoverability guard was also added to build and verify. Both changes are in place.

## Source and rights

- Trace page and license: <https://github.com/google/cluster-data/blob/master/ClusterData2011_2.md>
  - Live sha256 `e189e6d6716603855707238eab489f54163620310f46683ff521a5c1922050a1`, identical to the pinned copy.
  - Grant: "The data and trace documentation are made available under the CC-BY [4.0] license."
  - The same page names the bucket `clusterdata-2011-2`.
- Bucket: `gs://clusterdata-2011-2`, read over anonymous HTTPS at `storage.googleapis.com/clusterdata-2011-2/`.
- Files fetched:
  - `task_usage` parts 0-4 of 500: 447,636,149 bytes, sha256-pinned from the bucket's own `SHA256SUM`, size and md5 checked against the GCS listing.
  - A 256 KiB head range of part 5, used only to prove where the trailing window ends.
  - `schema.csv`, `README` and `SHA256SUM`, all sha256-pinned.
- License: CC-BY-4.0.
- No credentials. No personal data: the publisher-obfuscated job, task and machine IDs are not emitted.

## Shape and conversion

Each natural record is one 5-minute cluster measurement window. It holds every `task_usage` row whose measurement period starts in `[w, w + 300 s)`, kept in source row order.

- Windowing:
  - The five parts are read as one start-time-sorted stream. Monotonicity is asserted, and windows must be exactly 300 s apart.
  - The stream must start at the trace start (600 s).
  - Windows that straddle a part cut (5,400, 10,500, 15,600 and 20,400 s) are joined.
  - The trailing window 25,500 s continues into part 5, so its 138,777 rows are dropped.
- Conversion: fields 16 (CPI) and 17 (MAI) are converted with `float(token)`, cast to IEEE binary32 and written little-endian.
- Missing values: empty fields are dropped per series and counted (`empty_fields_dropped`), never filled.
- Width-honesty guard: `f16_recoverable_fraction` must be at most 0.90. The build computes it; verify recomputes it from the stored bytes and requires equality with the index.
- Excluded columns: IDs, timestamps, flags, CPU rate and the memory, disk and page-cache columns.

## Accepted output

| Quantity | Value |
|---|---|
| Rows read | 12,210,234 |
| Rows emitted | 12,071,457 |
| Rows dropped (trailing partial window) | 138,777 |
| Complete windows | 83 (600..25,200 s, about 6.9 h) |
| Rows per window | 132,760–169,197 (median 144,791) |
| Primary samples | 166 (83 per series) |
| Primary values | 20,950,657 |
| Primary bytes | 83,802,628 |
| Median sample (gate) | 125,555.5 values |

| Series | Samples | Values | Bytes | Values per sample (median) | Range | Empty dropped | f16-recoverable per sample |
|---|---|---|---|---|---|---|---|
| `task_cycles_per_instruction_f32` | 83 | 10,806,180 | 43,224,720 | 119,083–147,990 (129,718) | 0.0695–1599 | 1,265,277 (10.5%) | 0.5624–0.6064 |
| `task_memory_accesses_per_instruction_f32` | 83 | 10,144,477 | 40,577,908 | 111,937–138,745 (121,823) | 0–2.0 | 1,926,980 (16.0%) | 0.4969–0.5498 |

Breadth (zlsim, measured by the driver): OK.

- CPI: nearest is the wwpdb structure-factor amplitude family at distance 0.0578, compressor loss 0.026.
- MAI: nearest is the same wwpdb family at distance 0.0699, compressor loss 0.039.

Both series compress about as well as existing decimal-printed f32 families (losses under 3% against wwpdb and sgemm), but their feature distance stays above 0.05. The redundancy rule needs both conditions, so neither series is redundant.

## Judge checks

- **Gate:** `python3 tools/autocollect/gate.py staging/google_clusterdata2011_task_usage_f32` passed with no warnings (166 samples, width 32).
- **Verify:** I ran `bash staging/google_clusterdata2011_task_usage_f32/verify.sh` myself. Exit 0; output: "verify ok samples=166 windows=83 rows=12071457 … primary_bytes=83802628".
- **Local-only build:** build.sh and verify.sh contain no network calls and only sha-check and parse local inputs.
- **Exact match to source:** my own parser read the head of part 0. The first 44,863 CPI and 42,645 MAI values of `w000600` equal float32 of the source tokens.
- **Distributions** (5 windows per series):
  - CPI: median about 3.2, p99 about 26.
  - MAI: median about 0.008, p99 about 0.126.
  - Largest top-value share 0.08%. CPI has 12.9k+ distinct values per window and MAI 20.5k+.
- **Width honesty:**
  - Rounding to m mantissa bits recovers CPI at 57%, 98.5% and 100% for m = 10, 12 and 13.
  - MAI recovers at 46%, 90% and 100% for m = 10, 12 and 14.
  - That is decimal 4-significant-digit structure with no float16 cliff, so float32 is the smallest standard width.
  - My recompute of f16_recoverable_fraction for CPI `w000600` (0.59050) equals the index value.
- **Near-duplicates:** all 166 sha256 values are unique. Adjacent windows agree at the same position on only 0.04–0.09% of values, with the longest equal run being 2.
- **Rights:** I fetched the live license page. It is byte-identical to the pinned copy, and the CC-BY clause and the bucket name are both present.
- **Novelty:**
  - `novelty.py --url storage.googleapis.com/clusterdata-2011-2`: no URL matches.
  - `novelty.py --url github.com/google/cluster-data`: no matches.
  - Term searches (clusterdata, borg, cycles/memory accesses per instruction, task_usage, cluster trace, performance counter, datacenter, alibaba): only this draft and its ledger row; nothing in the registry or downstream.
  - `--type vm_telemetry`: only azure_vm2019 (f64).
  - `--instrument` and `--archive`: 0 members each.
- **Caveats** (documented in the README, not blocking):
  - Coverage is a contiguous 6.9 h prefix of a 29-day trace (Sunday evening), not diurnally balanced.
  - Publisher-acknowledged CPI/MAI outliers are kept as published.
  - Low mantissa bits carry decimal-rounding structure from the 4-digit CSV printing.
  - Cosmetic nit: the header comment on line 3 of `build.sh` still mentions CPU rate among the emitted measures. Code, manifest and README are correct; a one-word follow-up edit is advisable.
