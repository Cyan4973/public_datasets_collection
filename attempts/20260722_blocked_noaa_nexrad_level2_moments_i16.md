# Blocked: noaa_nexrad_level2_moments_i16 — 403 ListBucket

- Date: 2026-07-22
- Candidate: `staging/noaa_nexrad_level2_moments_i16`
- Domain: weather radar Level-II base moments, int16

## Attempt

```
bash staging/noaa_nexrad_level2_moments_i16/download.sh
```

Log tail:

```
error 403: NEXRAD prefix listing failed for 2024/05/20/KTLX/.
This bucket may deny ListBucket from this environment. Provide exact object keys
with NEXRAD_KEYS_FILE=/path/to/keys.txt
```

## Reason

`noaa-nexrad-level2.s3.amazonaws.com/?list-type=2&prefix=...` returns 403 in this environment, denying ListBucket. Script correctly falls back to requiring `NEXRAD_KEYS_FILE`.

## Retry

- Provide exact keys file, e.g., `2024/05/20/KTLX/KTLX20240520_000000_V06` etc., 8 files <200MB each, or
- Use NCEI HTTP directory `https://www.ncei.noaa.gov/data/nexrad-level-2/2024/05/20/KTLX/` with href scraping for `_V06` suffix, which does not need S3 ListBucket.

Parser for Level-II moments (int16) is implemented and expects AR2V/ARCHIVE2 marker.

