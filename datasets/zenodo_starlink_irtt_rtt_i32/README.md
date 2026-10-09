# Starlink IRTT probe RTT and receive delay — int32 nanoseconds

Source: Zhao and Pan, *Starlink Latency and Downlink Throughput Measurement
Dataset*, Zenodo record 10020034 (v20230917), CC BY 4.0,
DOI 10.5281/zenodo.10020034.

A Starlink dish in Victoria, BC (ground station / PoP in Seattle) sends IRTT
UDP probes every 10 ms to a server in GCP `us-west1-a`. A session lasts two
minutes and starts every 10 minutes, for five days (2023-09-13 to
2023-09-17). Both hosts are NTP-synced to Google Public NTP. Each session
yields about 11,800 probes.

## Emitted series (all primary, int32 little-endian, nanoseconds)

| series | source field | meaning |
| --- | --- | --- |
| `irtt_rtt_ns_i32` | `round_trips[].delay.rtt` | round-trip delay |
| `irtt_receive_delay_ns_i32` | `round_trips[].delay.receive` | one-way downstream delay (clock-sync dependent) |

Each series gets one sample per IRTT session (`irtt-10ms-2m-<UTC ts>.bin`),
with values in probe order. Upstream values are Go int64 JSON integers. Each
one is range-checked into signed int32 and stored unchanged. Values sit in
the tens to hundreds of milliseconds (about 25-29 bits), so they use the
upper bytes. Signed storage allows for negative one-way delays caused by
clock offsets.

IRTT computes `rtt` from monotonic clocks minus server processing time, and
the one-way delays from NTP-synced wall clocks. As a result,
`rtt ≈ send + receive` to within 1 µs for 89.5–98.0% of probes in every
session (median 95.1%, checked over all 716 sessions).

Not emitted: IPDV (a difference stream), wall and monotonic timestamps,
server processing time, the per-session summary statistics, and all
iPerf3 throughput files. Also not emitted: `delay.send`, the one-way upstream
delay. Given the identity above it is a near-duplicate view
(≈ `rtt − receive`), and the zlsim breadth gate measured it redundant against
downstream `gas_feat` (distance 0.0303, loss 1.88%).

## Missing values

Each field is taken from every round trip whose `delay` object contains it.
Probes lost upstream or downstream (`lost` in `true`, `true_up`,
`true_down`) carry no delay values. They are dropped, never filled. Each
index row records `probes_total`, `probes_dropped` and `lost_counts`. In
the probed session, all delay fields were present on exactly the 11,723
`lost == "false"` rows out of 11,794.

## Scripts

- `download.sh` checks the record's identity and CC BY 4.0 license, then
  fetches the README and the 1,169,608,066-byte `tar.zst` with resumable
  curl. It checks the Zenodo MD5 and that the payload is zstd-wrapped tar.
- `build.sh` runs `zstd -dc` into Python `tarfile` mode `r|`, so nothing is
  extracted to disk (the decompressed archive is 9.7 GB). It parses only the
  `data/<day>/irtt-*.json` members and fails unless all five dates are
  realized.
- `verify.sh` re-streams the archive and re-decodes every session. It
  byte-compares every sample, and checks each sample's count, sum, min and
  max against IRTT's own per-session `stats` block. It also rejects constant
  samples, stray files, any directory under `samples/<id>/` other than the
  two series directories, and manifest or index drift.

Requires the `zstd` CLI and Python 3.11+ (stdlib only).

```bash
bash staging/zenodo_starlink_irtt_rtt_i32/download.sh
bash staging/zenodo_starlink_irtt_rtt_i32/build.sh
bash staging/zenodo_starlink_irtt_rtt_i32/verify.sh
```

## Realized scope (build of 2026-10-08)

- 716 IRTT sessions: 140 on 2023-09-13 (the first folder starts at
  00:40 UTC), then 144 on each of 09-14 to 09-17. All 716 iPerf3 members
  were skipped.
- 2 series × 716 samples = 1,432 samples. Each series has 8,281,945 values
  (33,127,780 bytes). Primary total: 16,563,890 values, 66,255,560 bytes.
- Values per sample: min 9,049, median 11,656, max 11,778.
- Probes: 8,442,699 total, of which 8,281,945 have `lost == "false"`.
  Dropped: 133,645 `true_up`, 24,189 `true_down` and 2,920 `true`. Every
  emitted delay came from a `lost == "false"` row, so the two series are
  aligned per session.
- Ranges (ns): rtt 20,343,842 to 782,927,963; receive 4,376,340 to
  737,217,941. No negative one-way delays
  occurred.
- Aggregate SHA-256 (over per-sample SHA-256 values, sorted by session):
  rtt `41b7b66c…f669`, receive `f5184d15…350e`.
  Full values are in `filtered/<id>/ingest_stats.json`.
