# Starlink IRTT probe RTT and receive-delay int32 development

## Outcome

Accepted `zenodo_starlink_irtt_rtt_i32` from the single-version Zenodo record 10020034 (v20230917): *Starlink Latency and Downlink Throughput Measurement Dataset* by Zhao and Pan, University of Victoria.

This is the corpus's first per-packet active network-latency time series. The network domain already holds flow-feature tables downstream (UNSW-NB15, KDD99, CICIDS2017), CESNET aggregate traffic bytes and Zero-SWARM TCP/Modbus header fields. None of them is a delay series measured probe by probe. The novelty is therefore a new quantity, not a new modality.

The first submission had three series: rtt, send and receive. IRTT reports rtt ≈ send + receive to within 1 µs for 89.5–98% of probes in every session, and zlsim measured the send series redundant against downstream `gas_feat` (distance 0.0303, loss 1.88%). Repair cycle 1 removed the send series. The rtt and receive bytes did not change.

## Source and rights

- Source: Zenodo record 10020034, `data-20230913-20230917.tar.zst`
- Compressed bytes: 1,169,608,066; Zenodo MD5 `7c1fecd817616b49eecd414ecda31c6d`
- README.txt: 3,649 B, MD5 `4c3cd21a6757c266b301997dfaebc340`
- License: CC BY 4.0. The record metadata states `license.id = cc-by-4.0` with open access, and download.sh re-checks this on every run. The upstream README asks users to cite DOI 10.5281/zenodo.10020034 and the PIMRC'23 paper (arXiv:2307.06863).
- Setup:
  - A Starlink dish in Victoria, BC (Seattle PoP) probes an IRTT server in GCP `us-west1-a` over UDP every 10 ms.
  - Each session lasts 2 minutes, and a session starts every 10 minutes, from 2023-09-13 to 2023-09-17.
  - Both hosts are NTP-synced to Google Public NTP.
  - Server addresses were redacted upstream. The client address is private RFC1918 and is not emitted.

## Shape and conversion

Each natural record is one IRTT client session JSON, `data/<day>/irtt-10ms-2m-<ts>.json`. The archive is streamed through `zstd -dc` into `tarfile` mode `r|` and never extracted to disk (it is 9.7 GB decompressed). iPerf3 members are skipped.

For each session there are two samples:

- `irtt_rtt_ns_i32`: `round_trips[].delay.rtt`. IRTT computes it from monotonic clocks minus server processing time.
- `irtt_receive_delay_ns_i32`: `round_trips[].delay.receive`, the client receive wall time minus the server send wall time. It depends on clock sync.

The upstream values are Go int64 nanosecond JSON integers. Each value is type-checked as an integer and range-checked into signed int32, then stored unchanged as little-endian int32, in seqno order. Lost probes (`true_up`, `true_down`, `true`) have empty `delay` objects upstream. They are dropped and counted in the index, never filled, so the two series stay aligned per session. `delay.send` is omitted as a near-duplicate view (≈ rtt − receive). Also not emitted: IPDV, timestamps, server processing time and the iPerf3 throughput files.

## Accepted output

- Sessions: 716 (140 on 2023-09-13, which starts at 00:40 UTC, then 144 on each of 09-14..09-17)
- Primary series: 2 (rtt, receive), each with 716 samples, 8,281,945 values and 33,127,780 bytes
- Primary total: 1,432 samples, 16,563,890 values, 66,255,560 bytes
- Values per sample: min 9,049, median 11,656, max 11,778
- Probes: 8,442,699 total, of which 8,281,945 are valid; dropped 133,645 `true_up`, 24,189 `true_down` and 2,920 `true`
- Ranges (ns): rtt 20,343,842..782,927,963; receive 4,376,340..737,217,941; no negatives
- Aggregate SHA-256:
  - rtt `41b7b66cf4a787fbc36e9e83c980a243cc22212579bb29377dc3e761d8aaf669`
  - receive `f5184d153b2b82516c1b4689e28d86363e02d92a0687d2ced019c6233feb350e`
- Breadth (zlsim, post-repair): verdict OK
  - rtt: nearest `downstream:appl_rv`, distance 0.0303, loss 5.01%
  - receive: nearest `downstream:gas_feat`, distance 0.0411, loss 3.19%
  - no fill warnings; mode share 0.0002

## Judge checks

- **Gate:** `python3 tools/autocollect/gate.py staging/zenodo_starlink_irtt_rtt_i32` passed with no warnings.
- **Verify:** I ran `verify.sh` myself (exit 0, 2m28s). All 16,563,890 values were byte-compared to a fresh decode of the pinned archive. Each session's count, sum, min and max matched IRTT's own upstream `stats.rtt` and `stats.receive_delay` blocks. The extra-directory check is in place. build.sh reads only the local archive.
- **Bytes** (8 samples per series, read with `struct`):
  - Ranges are physically plausible: Starlink RTT of tens to hundreds of ms, downlink one-way of 4–237 ms per session.
  - Values use 27–29 bits.
  - The last decimal digit is uniform, so this is true nanosecond resolution.
  - There are no negatives and no duplicate files, and the mode count is 2 per session.
  - My independent decode of the first archive member matched both samples exactly.
  - corr(rtt, receive) = 0.64: related, but not duplicates.
- **Rights:** I read the downloaded `record.json` (license `cc-by-4.0`, open access, files list contains the pinned archive) and `README.txt`. The Zenodo versions API shows one version, so the full population is collected. No credentials are in any script, and no personal data is emitted.
- **Novelty:** `novelty.py` with the record URL and terms (starlink, irtt, round-trip, latency) found no prior family. The type, instrument and archive queries all returned 0. The downstream lists at all widths contain network flow-feature tables but no per-probe latency series.
- **Repair applied as instructed:** the send series is gone from build, verify, manifest and README. The build calls `rmtree` on the samples tree. The manifest and README document the rtt ≈ send + receive identity. The rtt and receive SHA-256 values match the pre-repair build.
- **Host cap:** zenodo.org is a general repository host, and the driver enforces its own archive-host cap.
