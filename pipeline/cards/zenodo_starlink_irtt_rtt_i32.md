# Starlink (Victoria BC -> GCP us-west1) IRTT 10 ms UDP Probe Round-Trip and One-Way Delays, Nanosecond Int32 per 2-Minute Session

- Candidate id: `zenodo_starlink_irtt_rtt_i32`
- Width: int32
- Quantity: Per-packet network latency in nanoseconds measured by IRTT: delay.rtt (round-trip), delay.send and delay.receive (NTP-synced one-way delays), one value per 10 ms UDP probe
- Source: https://zenodo.org/records/10020034
- Resources: https://zenodo.org/api/records/10020034/files/data-20230913-20230917.tar.zst/content, https://zenodo.org/api/records/10020034/files/README.txt/content
- License: CC-BY-4.0
- License evidence: https://zenodo.org/api/records/10020034
- License quote: Zenodo record metadata: "license": {"id": "cc-by-4.0"}; README: 'If you used this dataset in your research, please cite this Zenodo dataset with DOI 10.5281/zenodo.10020034'
- Natural record: One IRTT client session JSON (data/<day>/irtt-10ms-2m-<timestamp>.json): a 2-minute run at 10 ms probe interval, ~11,800 round_trips of which ~11,700 carry delay values (probe file: 11,794 round trips, 71 lost, RTT 23.2-129.5 ms)
- Estimated samples: 700
- Estimated primary values: 24,000,000
- Estimated download bytes: 1,169,608,066
- Estimated primary bytes: 98,000,000
- Decode path: curl the single tar.zst; `zstd -dc | tar -x` (zstd CLI is already an accepted tool path) or stream with tarfile over a zstd pipe; select only irtt-*.json members (iperf3-*.json skipped); json.load each; for each round_trip with lost=='false' take int delay.rtt / delay.send / delay.receive; check |v| < 2^31; struct.pack('<i'). Lost packets dropped and counted in the index (missing-value policy), never filled.
- Novelty kind: new_modality
- Measurement type: network_packet_latency
- Instrument line: irtt_udp_probe_starlink_dish
- Archive collection: zenodo.org/records/10020034
- Novelty evidence: novelty.py --url zenodo.org/records/10020034 --terms starlink irtt round-trip: no term matches in recipes, registry, ledger, downstream or downstream_registry (same Zenodo host only). The vocabulary has no packet-latency/RTT measurement type; closest network families are cesnet_ts24 traffic bytes (u64 aggregate counts) and zeroswarm TCP sequence numbers (u32 header fields) — neither is a delay measurement. Downstream 32-bit list has no latency family.
- Homogeneity: Single dish, single PoP (Seattle), single GCP target, fixed IRTT config (10 ms interval, 2 min sessions every 10 min) over 5 consecutive days. RTT, send-delay and receive-delay are three separate series, all int64-ns JSON integers in the 23-130 ms range (~25-27 bits used, genuinely 32-bit). IPDV (a difference stream) and wall/monotonic timestamps are excluded or auxiliary only.
- Risks: Download is one 1.17 GB tar.zst (9.7 GB decompressed, ~85% irtt JSON); if the per-candidate byte cap is lower, a byte-range prefix of the zstd stream decodes cleanly to the first days (members are date/alpha ordered, iperf3 files precede irtt files per day) — builder must then only keep complete members and state the realized date scope. Build-time JSON parsing of ~9 GB is slow but stdlib-only. One-way delays depend on NTP sync (may drift; could be negative rarely — use signed int32). Values are native JSON integers (Go int64 ns); storing as int32 is a range-checked narrowing, not a remap.
- Probe evidence: Zenodo API lists file data-20230913-20230917.tar.zst size 1,169,608,066. Range GET bytes 0-12,000,000 decoded with zstd to 154 MB of tar: members data/2023-09-13/iperf3-2m-*.json (~911 KB each) then irtt-10ms-2m-2023-09-13-00-40-00.json (13,643,695 B). Parsed it: keys version/system_info/config/stats/round_trips; 11,794 round_trips, e.g. delay {receive: 13776298, rtt: 27547053, send: 13770763}; 11,723 valid RTTs, min 23,209,789 ns, max 129,454,374 ns.

Proposed by the autocollect scout on 2026-10-08 (transcript `.data/pipeline/logs/scout_32bit/scout.20261008_162828.jsonl`).
