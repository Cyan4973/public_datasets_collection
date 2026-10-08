# Google Borg Cluster Trace 2011 (clusterdata-2011-2) Task Usage: CPU Rate, Cycles-per-Instruction and Memory-Accesses-per-Instruction per 5-Minute Window, Float32

- Candidate id: `google_clusterdata2011_task_usage_f32`
- Width: float32
- Quantity: Per-task resource usage measured by Borg over a 5-minute window: mean CPU rate (normalized core-seconds/s), cycles per instruction (CPI) and memory accesses per instruction (MAI) from hardware performance counters
- Source: https://github.com/google/cluster-data/blob/master/ClusterData2011_2.md
- Resources: https://storage.googleapis.com/clusterdata-2011-2/task_usage/part-00000-of-00500.csv.gz, https://storage.googleapis.com/storage/v1/b/clusterdata-2011-2/o?prefix=task_usage/, https://storage.googleapis.com/clusterdata-2011-2/schema.csv
- License: CC-BY-4.0
- License evidence: https://github.com/google/cluster-data/blob/master/ClusterData2011_2.md
- License quote: The data and trace documentation are made available under the CC-BY license. By downloading it or using them, you agree to the terms of this license.
- Natural record: One cluster-wide measurement-window snapshot: all task_usage rows sharing one 300-s-aligned start time (every task running on the ~12.5k-machine cell in that window), in source row order — the same fleet-timestamp-snapshot shape accepted for azure_vm2019_cpu_utilization_readings_f64. Expect ~100k-150k rows per window.
- Estimated samples: 80
- Estimated primary values: 36,000,000
- Estimated download bytes: 450,000,000
- Estimated primary bytes: 144,000,000
- Decode path: curl the first ~5 sequential task_usage part files (each ~87-92 MB gzip, md5 in GCS JSON listing); gzip+csv stdlib; group contiguous rows by start time (col 1) on the 300,000,000-us lattice, merging a window that straddles a part boundary and dropping the trailing partial window; emit columns 6 (CPU rate), 16 (CPI), 17 (MAI) as struct '<f'; empty fields (CPI/MAI absent on some machines) are dropped and counted per sample, not filled. Rows with irregular (non-lattice) start times are documented and either excluded or kept as their own windows.
- Novelty kind: new_source
- Measurement type: cluster_task_resource_usage
- Instrument line: google_borg_task_usage_monitor
- Archive collection: storage.googleapis.com/clusterdata-2011-2
- Novelty evidence: novelty.py --url storage.googleapis.com/clusterdata-2011-2/task_usage/ --terms 'cluster trace' 'cycles per instruction' borg: no term matches anywhere (recipes, registry, ledger, downstream); URL hits are only the generic storage.googleapis.com host used by unrelated buckets. No downstream 32-bit cluster/CPU family. Closest local material is azure_vm2019 CPU utilization at 64-bit (different provider, VM-level percent, f64); CPI and MAI hardware-counter series have no analogue in the corpus.
- Homogeneity: One cell, one trace release, one monitoring pipeline; each series is one quantity (CPU rate, CPI, MAI) with one unit and normalization; windows share the 5-minute lattice. Memory columns, ids, timestamps and flags are excluded (or auxiliary).
- Risks: Source CSV prints ~4 significant digits, so f32 is the honest width but low-precision decimals could look compressible; CPI and MAI are the most distinctive columns, CPU rate alone may sit closer to other utilization material. Window grouping depends on rows being start-time ordered within parts (observed for part 0 prefix; builder must assert). Generic GCS host storage.googleapis.com is shared with other accepted Google buckets. Download of 5 parts ~450 MB; more parts scale linearly.
- Probe evidence: GCS JSON listing (maxResults=20) shows task_usage/part-00000..-of-00500.csv.gz, sizes 91,723,415 / 87,188,987 / 90,861,131 with md5Hash. schema.csv confirms task_usage fields 1-20 (6 CPU rate FLOAT, 16 cycles per instruction FLOAT, 17 memory accesses per instruction FLOAT). Range GET 0-200,000 of part 0 decompressed to 5,328 rows all with start time 600000000, e.g. '600000000,900000000,3418309,0,4155527081,0.001562,...,2.445,0.007243,0,1,0' (CPI 2.1-5.6, MAI 0.005-0.02).

Proposed by the autocollect scout on 2026-10-08 (transcript `.data/pipeline/logs/scout_32bit/scout.20261008_162828.jsonl`).
