# CESNET-TimeSeries24 ISP Institution-Level 10-Minute Transmitted Bytes (n_bytes) UInt64

- Candidate id: `cesnet_ts24_institution_traffic_bytes_u64`
- Width: uint64
- Quantity: Bytes transmitted per 10-minute window, summed over all IP flows of one institution on the Czech CESNET3 research/education ISP backbone, over 40 weeks. The source aggregates IP flow records (66 billion flows, ~3.7 PB) into these windows. This is a native unsigned byte counter (IPFIX octet counters are unsigned64).
- Source: https://zenodo.org/records/13382427
- Resources: https://zenodo.org/records/13382427/files/institutions.tar.gz, https://zenodo.org/records/13382427/files/times.tar.gz, https://zenodo.org/api/records/13382427
- License: CC-BY-4.0
- License evidence: https://zenodo.org/records/13382427
- License quote: Zenodo record 13382427 metadata: license id 'cc-by-4.0' (Creative Commons Attribution 4.0 International). The authors (Koumar, Hynek, Čejka, Šiška; Sci Data 12, 338 (2025)) ask users to cite the paper.
- Natural record: One institution's 10-minute time series: institutions/agg_10_minutes/<id>.csv. There are 283 institutions (identifiers.csv); each has up to 40,320 windows (40 weeks × 1,008). The primary series is the n_bytes column. id_time is an auxiliary window index; times.tar.gz maps it to timestamps.
- Estimated samples: 283
- Estimated primary values: 11,400,000
- Estimated download bytes: 479,428,489
- Estimated primary bytes: 91,000,000
- Decode path: curl the Zenodo file and pin md5 ab3e15fb8dc9b7120ddb2318795b6812 (479,428,489 B). Read it with stdlib tarfile in streaming mode ('r|gz') and keep only members under institutions/agg_10_minutes/. Parse with the csv module, convert the n_bytes column with int() and pack with struct '<Q'. Reject negative or non-integer values. Pure stdlib.
- Novelty kind: new_modality
- Novelty evidence: novelty.py --url https://zenodo.org/records/13382427 --terms CESNET 'network traffic' n_bytes found a same-host (zenodo.org) match only. Nothing in the registry, ledger, downstream families or downstream registry. No network traffic-volume telemetry exists in the local corpus or downstream at any width; the nearest families, clickbench and gharchive, are web/event logs, not traffic counters.
- Homogeneity: One metric (n_bytes), one aggregation window (10 min), one entity level (institution), one network and one 40-week period. Do not mix in the agg_1_hour/agg_1_day re-aggregations, the institution_subnets or ip_addresses levels (different scales), or the other CSV columns: n_packets and n_flows are different units, and the ratios and averages are rounded to 2 decimals and not 64-bit material.
- Risks: (1) Width honesty is the main risk. A 6 MB prefix sample of 19 institutions' hourly files showed ~21% of hourly values above 2^32 (max 8.1e11). Scaled to 10 minutes, that is roughly 9% above 2^32, concentrated in the largest institutions; small institutions stay in the u32 range. Defense: these are native 64-bit octet counters, the values span 1e3 to 1e11 and are heavy-tailed, and no narrower integer type holds them. Fallback: use agg_1_hour (6,717 values per institution, ~21% above 2^32, ~1.9M values in total). (2) A few windows are missing (hourly files had 6,709-6,717 of 6,720 rows). Emit present windows in order and keep id_time as the auxiliary alignment. (3) The tar also holds hourly and daily copies, so the extraction ratio is about 1/5; acceptable at 479 MB.
- Probe evidence: The Zenodo API lists institutions.tar.gz at 479,428,489 B with md5 ab3e15fb8dc9b7120ddb2318795b6812, license cc-by-4.0. A range GET of the first 6 MB stream-decompressed tar members: directories institutions/agg_10_minutes/, agg_1_hour/, agg_1_day/; identifiers.csv lists 283 ids (0..284). Header: id_time,n_flows,n_packets,n_bytes,... Example hourly rows: '0,493287,24425836,22650855016,...'. Per-institution hourly n_bytes ranges include 2.8e9..1.95e11, 3.2e9..8.1e11 and 6.2e4..4.4e9.

Proposed by the autocollect scout on 2026-10-06 (transcript `.data/pipeline/logs/scout_64bit/scout.20261006_012600.jsonl`).
