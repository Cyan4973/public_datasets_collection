# google_clusterdata2011_task_usage_f32

Per-task resource-usage measurements from the Google Borg cluster trace
`clusterdata-2011-2`: 29 days of one ~12.5k-machine cell from May 2011,
version 2.1, published under CC-BY 4.0. Two hardware-counter measures from
the `task_usage` table are kept: cycles per instruction (CPI) and memory
accesses per instruction (MAI). Each is emitted as float32, one sample per
5-minute measurement window. CPU rate is deliberately not emitted (see
Precision).

## Source

- Trace page and license: <https://github.com/google/cluster-data/blob/master/ClusterData2011_2.md>.
  It says: "The data and trace documentation are made available under the
  CC-BY license."
- Bucket: `gs://clusterdata-2011-2`, read anonymously over
  `https://storage.googleapis.com/clusterdata-2011-2/...`. Other accepted
  recipes also use the `storage.googleapis.com` host, but for different
  buckets. This one is its own bucket, and no other recipe uses it.
- `task_usage` has 500 gzip CSV parts (42.1 GB). Together they form one row
  stream sorted by start time, cut by trace time at about 5,011 s per part.
  This recipe fetches parts 0-4 (447,636,149 bytes) plus a 256 KiB head range
  of part 5. Sizes and md5 come from the GCS JSON listing; sha256 comes from
  the bucket's own `SHA256SUM`.

## Natural record: one 5-minute cluster window

Borg reports each task's usage over periods inside 300 s windows. The trace
starts at 600 s, so windows are 600, 900, 1,200 s and so on. A row belongs to
the window `floor(start_time / 300 s)`. A window contains:

- rows that start on the window boundary (normally full 300 s periods), then
- rows whose period starts inside the window (a task that started, finished
  or was rescheduled mid-window produces a partial period).

Both kinds are measurements of the same window, and both are kept in source
row order. Per-window counts of each kind are recorded in
`filtered/<id>/ingest_stats.json`.

- Part cuts fall inside windows: parts 1-4 start at 5,612, 10,623, 15,634 and
  20,645 s. The window that straddles each cut is joined across the two
  parts.
- Start times are asserted never to decrease across the whole part stream,
  and consecutive windows must be exactly 300 s apart.
- The leading window (600 s) starts exactly at the trace start, so it is
  complete and kept. A probe of the head of part 0 showed 144,348 rows in
  that window, 131,320 of them lattice-aligned.
- The trailing window (25,500 s) continues into part 5, whose head starts at
  25,656 s, so it is dropped.
- Result: **83 complete windows**, 600 s to 25,200 s (about 6.9 hours).

## Realized output (build 2026-10-08)

- **Rows:** 12,210,234 read; 12,071,457 emitted; 138,777 dropped as the
  trailing partial window 25,500 s.
- **Windows:** 132,760-169,197 rows each (median 144,791).
- **Straddling windows** (joined across a part cut): 5,400, 10,500, 15,600
  and 20,400 s.
- **Samples:** 166 (83 per series), 83,802,628 primary bytes:
  - CPI: 10,806,180 values (43,224,720 bytes); 1,265,277 empty fields dropped
    (10.5%). Range 0.0695-1599; the publisher acknowledges outliers. At least
    12,888 distinct values per window. f16_recoverable_fraction per sample
    0.5624-0.6064.
  - MAI: 10,144,477 values (40,577,908 bytes); 1,926,980 empty fields
    dropped (16.0%). Range 0-2.0. At least 20,536 distinct values per window.
    f16_recoverable_fraction per sample 0.4969-0.5498.
- **Anomaly counters:** no negative values, no rows with end <= start, no
  rows whose period ends beyond its window.

## Series (all primary, float32 LE)

| series | source field | notes |
|---|---|---|
| `task_cycles_per_instruction_f32` | 16 cycles per instruction | empty in ~11% of rows; implausible outliers kept as published |
| `task_memory_accesses_per_instruction_f32` | 17 memory accesses per instruction | empty in ~17% of rows |

- **Empty fields:** dropped from that series' sample, never filled, and
  counted per sample (`empty_fields_dropped`). The two series therefore
  have different value counts per window.
- **Not emitted:** IDs, timestamps, flags (aggregation type), sample portion,
  CPU rate, memory, page-cache and disk columns, and sampled CPU usage.
- **Precision and width honesty:**
  - CPI and MAI need float32. About 42% (CPI) and 49% (MAI) of the values do
    not survive a float16 round trip at 4 significant digits.
  - Field 6 CPU rate was excluded. It is a source code of 16 bits or fewer:
    a fixed 2^-20 grid below about 5e-4, a 9-bit mantissa above, and 100% of
    its values recover from float16. Storing it as float32 would be a
    gratuitous widening.
  - Guard: every sample records `f16_recoverable_fraction`, the share of
    stored float32 values v with `abs(v) < 65504` and
    `float('%.4g' % h) == float('%.4g' % v)`, where h is the float16 round
    trip of v. The build fails above 0.90. Verify recomputes it from the
    stored bytes, requires it to equal the index value, and applies the same
    limit.

## Scripts

- `discover.sh`: metadata-only. Shows how the parts, checksums and
  part-boundary start times were resolved.
- `download.sh`: fetches and checks the inputs.
  - The license page is content-checked.
  - `schema.csv`, `README` and `SHA256SUM` are sha256-pinned.
  - The GCS listing check is best effort.
  - The five parts are resumable with stall detection, sha256-pinned, and
    their first start times are checked.
  - The part-5 head range is checked via Content-Range and sha256.
- `build.sh` → `scripts/build_windows.py`: writes the samples, the index and
  the ingest stats.
- `verify.sh` → `scripts/verify_windows.py`: an independent re-derivation
  using raw zlib, integer windowing and `struct '<f'`. Every sample must be
  byte-identical, and the script re-checks the index stats (including the
  float16-recoverability guard), the stats counters, stray files and the
  manifest totals.

The parsers were self-tested on synthetic parts (straddling windows,
mid-window rows, empty fields, a dropped trailing window, a tamper test). The
build was also run on real rows from the head of part 0.

## Caveats

- The coverage is the first ~6.9 h of a 29-day trace (Sunday evening, US
  Eastern). It is a contiguous prefix chosen for boundedness, not a
  diurnally balanced sample.
- CPU rate, the most familiar utilization quantity, is not included (see
  Precision), so this family covers hardware-counter efficiency (CPI and
  MAI) only. Those series have no analogue in the corpus.
- The CSV prints about 4 significant digits, so the float32 low-order
  mantissa bits carry decimal-rounding structure rather than full binary32
  precision.
