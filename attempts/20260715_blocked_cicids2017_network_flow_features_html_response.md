# Blocked Attempt: `cicids2017_network_flow_features_f64`

Date: 2026-07-15

## Outcome

The direct CICIDS2017 MachineLearningCSV URL did not return a ZIP archive. It
returned an HTML UNB dataset page of 108,784 bytes, and local ZIP validation
failed with `zipfile.BadZipFile`.

## Evidence

The failed URL was:

```text
http://205.174.165.80/CICDataset/CIC-IDS-2017/Dataset/CIC-IDS-2017/CSVs/MachineLearningCSV.zip
```

The saved file began with:

```text
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" lang="en">
```

## Decision

Treat this CICIDS2017 direct URL as blocked until a verified current archive URL
is available. The next staged cybersecurity fallback is
`kddcup99_network_intrusion_features_f64`.
