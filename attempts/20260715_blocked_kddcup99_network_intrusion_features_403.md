# Blocked Attempt: `kddcup99_network_intrusion_features_f64`

Date: 2026-07-15

## Outcome

The KDD Cup 1999 direct gzip URL returned `403` during the user-run download.
No dataset payload was saved.

## Failed URL

```text
https://kdd.ics.uci.edu/databases/kddcup99/kddcup.data_10_percent.gz
```

## Decision

Treat this source as blocked until a verified mirror is available. The next
staged fallback is `magic_gamma_telescope_event_features_f64`, using a small
direct UCI archive file from a different scientific instrument domain.
