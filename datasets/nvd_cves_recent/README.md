# NVD CVEs Recent

Bounded 2024 NVD CVE metadata recipe. The repaired recipe replaces the old
single January first-page slice with paginated monthly NVD API windows.

Run:

```bash
datasets/nvd_cves_recent/download.sh
datasets/nvd_cves_recent/build.sh
datasets/nvd_cves_recent/verify.sh
```

The downloader is cache-aware and uses anonymous NVD API access by default. It
waits `6` seconds between fresh API requests to respect NVD's public rate-limit
guidance. If an API key is available, set `NVD_API_KEY`; this is optional and is
not required for reproducibility.

Default scope:

- year: `2024`
- windows: one request series per month
- page size: `2000`
- natural sample boundary: one homogeneous CVE field sequence sorted by CVE
  publication timestamp
- primary fields: published timestamp, last-modified timestamp, reference
  count, CVSS base score scaled by 10, primary CWE id, and CPE match count

The build rejects malformed pages, tiny output, constant primary series, and
outputs above the repository `1 GB` primary payload cap.
