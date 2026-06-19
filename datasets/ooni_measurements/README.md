# OONI Web Connectivity Measurements

Bounded OONI measurement-list corpus for the `web_connectivity` test. The
recipe replaces the old latest-page snapshot with a fixed January 2024 time
window and paginated API offsets.

Pinned source pattern:

- `https://api.ooni.io/api/v1/measurements?test_name=web_connectivity&since=2024-01-01T00%3A00%3A00Z&until=2024-02-01T00%3A00%3A00Z&limit=1000&offset={offset}`

Default download scope:

- test name: `web_connectivity`
- time window: `2024-01-01T00:00:00Z` through `2024-02-01T00:00:00Z`
- request up to `OONI_TARGET_RECORDS=20000` source records
- require at least `OONI_MIN_COMPLETE_RECORDS=10000` records with all selected
  measurement fields

Validated local run:

- source pages: 20
- source records: 20,000
- source bytes: 14,124,960
- retained measurements: 20,000
- unique measurement IDs: 20,000
- unique probe ASNs: 186
- `scores.blocking_general` distribution: 0.0=18,303, 1.0=1,504,
  2.0=192, 3.0=1
- primary samples: 3
- primary values: 60,000
- primary sample bytes: 240,000
- primary sample size range: 20,000 values / 80,000 bytes for each sample

Selected primary series:

- `ooni_measurement_unix_u32`
- `ooni_probe_asn_u32`
- `ooni_blocking_general_score_f32`

Missing-value policy: records missing measurement start time, probe ASN, or
`scores.blocking_general` are dropped as a record unit so all three samples
remain aligned over the same measurement axis.

Acceptance checks:

- at least 10,000 retained complete measurements
- at least 10,000 primary values
- at least 100 KB primary sample bytes
- median primary sample size at least 1,000 values
- no globally constant sample
