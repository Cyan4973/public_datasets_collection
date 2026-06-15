# OONI Measurements Snapshot

Pinned OONI measurements page with boolean flags, ASN, timestamps, and scores.

Pinned source: `https://api.ooni.io/api/v1/measurements?limit=100`

Selected series:
- `ooni_anomaly`
- `ooni_probe_asn`
- `ooni_measurement_unix`
- `ooni_blocking_general_score`

Missing-value policy: Filters out rows missing scores, probe ASN, or measurement start time.
