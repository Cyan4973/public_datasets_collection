# Azure Public Dataset V2 (2019) VM CPU Utilization, 5-Minute Fleet Snapshots, Float64

Per-VM CPU utilization readings from the Microsoft Azure 2019 VM trace
(`AzurePublicDataset` V2), the trace released with the Resource Central work
(SOSP'17). Every 5 minutes the trace records, for each running VM, the
minimum, maximum and average CPU utilization (percent) over that interval.
This recipe takes the first 88 complete 5-minute fleet snapshots of the trace
(t = 0 .. 26,100 s, files 1 and 2 of 195) and emits min, max and avg CPU as
three native float64 series, one sample per snapshot.

- Source page: <https://github.com/Azure/AzurePublicDataset/blob/master/AzurePublicDatasetV2.md>
- Files: GitHub release `dataset-v2` of `Azure/AzurePublicDataset`
  (the old Azure Blob URLs redirect there)
- Width: float64, native (`schema.csv` types the columns `DOUBLE`)

## License and citation

- The repository root `LICENSE` is the CC BY 4.0 legal code ("Attribution 4.0
  International"). The GitHub license API reports `spdx_id: CC-BY-4.0`. Code
  in the repository is separately under `LICENSE-CODE` (MIT).
- The trace files are release assets of that same repository. The
  repository's `AzureVMNoiseDataset2024.md` states: "The data is made
  available and licensed under a CC-BY Attribution License
  (https://github.com/Azure/AzurePublicDataset/blob/master/LICENSE)."
- `AzurePublicDatasetV2.md` has no separate license line. The grant relied on
  is the repository-level CC BY 4.0 `LICENSE`.
- `download.sh` re-fetches `LICENSE` on every run and fails if it is no longer
  the CC BY 4.0 text.
- Citation, as the repository README requests for both VM traces: Eli Cortez,
  Anand Bonde, Alexandre Muzio, Mark Russinovich, Marcus Fontoura, Ricardo
  Bianchini. "Resource Central: Understanding and Predicting Workloads for
  Improved Resource Management in Large Cloud Platforms." SOSP 2017.
  <https://www.microsoft.com/en-us/research/wp-content/uploads/2017/10/Resource-Central-SOSP17.pdf>

## Source structure

V2 is 30 consecutive days from one Azure region: 2,695,548 VMs and
1,942,780,023 CPU readings. The readings form one timestamp-sorted row stream.
That stream is cut into 195 gzip CSV files (166,566,456,024 bytes in total)
of exactly 10,000,000 rows each, except the last.

The cuts are by row count, not by timestamp, so a file boundary usually falls
inside a snapshot.

Each row has five fields: `timestamp,vm id,min cpu,max cpu,avg cpu`. Lines
end in CRLF and there is no header.

- The timestamp is in seconds from the trace start, on a 300 s grid.
- The vm id is a 64-character encrypted hash.
- The three CPU values are printed with 16-17 significant digits, e.g.
  `19.898441030801841`. These are full binary64 values, not rounded decimals.

## Natural record: the fleet snapshot

The natural record is one fleet snapshot: every VM reading that shares one
timestamp.

- **A per-VM series is not a bounded record here.** The files are
  timestamp-sorted, so any single VM's 30-day series is spread across all 195
  files (~166 GB). Re-assembling per-VM series would mean downloading the
  whole trace and inventing a local regrouping.
- **The timestamp snapshot is the unit the source is organized by.** The row
  stream is sorted by it, and a snapshot is one complete measurement round of
  the fleet: what a monitoring consumer reads at each 5-minute tick.
- **The files are not records.** They are arbitrary 10M-row pieces of the
  stream, so the recipe groups by timestamp across the file cut instead of
  treating a file as a sample.
- **Rows keep the source order inside a snapshot.** They are not sorted by
  vm id, which would be a local remap.

**Row order across snapshots.** Consecutive snapshots share about 99.8% of
their VMs, but the publisher's row order is effectively reshuffled every
snapshot. In a probe of t=0 versus t=300, only 1,911 of 227k positions held
the same VM. No VM's avg value repeats exactly between consecutive
snapshots. The samples are therefore not near-duplicates of each other. The
other side of this is that the order inside a sample carries no adjacency
structure. A sample is the fleet's utilization distribution in publisher
order.

Each snapshot holds 223,522-227,744 readings (median 226,171.5), so the
median sample is far above the 1,000-value floor. Per-snapshot row counts,
split by source file, are recorded in `filtered/<id>/ingest_stats.json`, and
each sample's count is its `value_count` in the index.

## Scope (bounded subset)

Files 1 and 2 are the first 20,000,000 rows of the stream, covering
timestamps 0..26,400 s. The recipe keeps the 88 complete snapshots
t = 0..26,100 s (7 h 20 min of trace time).

How the file cuts are handled:

- **Start.** t = 0 is the trace start, so the first snapshot is complete.
- **File 1/2 cut.** Snapshot t = 13,200 straddles it: its first 18,322 rows
  end file 1 and its other 207,895 rows begin file 2. Joined in stream order
  that is 226,217 rows, in line with its neighbours (226,086 and 226,194).
  It is emitted as one sample.
- **End.** The last 109,061 rows of file 2 have t = 26,400. A pinned 64 KiB
  head range of file 3 shows that file 3 starts at t = 26,400, so that
  snapshot continues there. It is incomplete and is dropped; this is the only
  exclusion. The same head range proves that t = 26,100 is complete.
- `build.sh` and `verify.sh` assert all of this, plus the row accounting:
  20,000,000 read = 19,890,939 emitted + 109,061 dropped.

**Realized output:** 3 series × 88 samples = 264 samples, 19,890,939 values
per series, 477,382,536 primary bytes (159,127,512 per series).

**Download:** 1,713,065,565 bytes for the two files, plus the 64 KiB range,
`schema.csv`, `LICENSE` and the release JSON. The driver measured
1,713,521,624 bytes in total.

**Why two files:** two files give 88 complete snapshots per series at under
half the 1 GB cap. A single file would give 44. More files would add more of
the same regime at ~240 MB per file.
- **Known limits:** the trace's timestamps are relative, so the wall-clock
  time of day is unknown. The scope covers only the first 7.3 hours of a
  30-day trace.

## Series

All three series share identical sample boundaries
(`samples/<id>/<series>/t<timestamp>.f64`) and row order.

| series | source field | meaning |
| --- | --- | --- |
| `vm_cpu_min_pct_f64` | field 3 `min cpu` | minimum CPU % within the 5-minute interval |
| `vm_cpu_max_pct_f64` | field 4 `max cpu` | maximum CPU % within the 5-minute interval |
| `vm_cpu_avg_pct_f64` | field 5 `avg cpu` | average CPU % over the 5-minute interval |

**Homogeneity.** Every series is the same quantity:

- CPU utilization, percent 0-100
- the same 5-minute aggregation
- one region and one trace: V2 (2019) only

The 2017 V1 trace (125 files, a different sanitized subset) is never mixed
in. min, max and avg are kept as separate series rather than interleaved.

**Dropped and auxiliary data.**

- The vm id column is dropped.
- The timestamp is the sample key. It is recorded in the index
  (`timestamp_s`) and in the file name, and is not a series.

## Conversion and checks

- **Conversion:** `float(token)` gives the exact binary64 the publisher
  printed. Values are written as raw little-endian float64 with no
  rescaling, rounding or narrowing.
- **Index statistics:** each index row carries `timestamp_s`,
  `snapshot_index`, `source_files` (two entries for t = 13,200),
  `min_value`/`max_value` (computed from the stored doubles),
  `distinct_values`, `zero_values` and `sha256`.
- **Realized values:**
  - min CPU spans 0..99.538 % (2,277 exact zeros); max CPU spans 0..100.0 %
    (4 zeros); avg CPU spans 0..99.593 % (4 zeros).
  - Every sample has at least 223,497 distinct values.
  - There are no `min <= avg <= max` violations and no duplicate VM ids.
- **Missing-value policy (build and verify):** any of the following is
  fatal. Nothing is imputed or filtered.
  - an empty, non-numeric, NaN/infinite or out-of-range value (outside
    [0, 100])
  - a malformed row
  - a timestamp gap or a reappearing timestamp
  - a duplicate vm id inside a snapshot
  - a constant sample

  Exact zeros are real readings and are kept. `min <= avg <= max`
  violations are counted in the stats, not altered.
- **Verify** uses a separate parser: raw zlib streaming, byte-level
  splitting and `struct` packing. It requires every sample file to be
  byte-identical to the re-derived column. It also re-checks the index
  statistics, the stats counters, the manifest totals and the absence of
  stray files.

## Files

- `download.sh`
  - checks the release API (best effort, rate limited) and the LICENSE text
  - fetches the pinned `schema.csv`
  - resumably fetches files 1 and 2 and the 64 KiB head range of file 3
  - curl is always re-invoked on the stable github.com URL, because the
    signed release-assets redirect expires
  - checks sha256 and the first-row timestamp of each file
- `build.sh` → `scripts/build_snapshots.py` (gzip + csv module, stdlib only).
- `verify.sh` → `scripts/verify_snapshots.py` (independent zlib/bytes parser).
- `discover.sh`: metadata-only probe showing how the asset ids, sizes, digests
  and boundary timestamps were resolved.

## Novelty

New modality for the corpus: cloud VM utilization telemetry. `novelty.py`
found no VM, CPU-utilization or cluster-trace material in `datasets/`,
`staging/`, the registry, the pipeline ledger or the downstream corpus at any
width. Its "azure" hits are unrelated WHO API recipes.
