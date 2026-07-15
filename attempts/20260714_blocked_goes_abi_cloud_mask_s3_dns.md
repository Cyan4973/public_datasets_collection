# goes_abi_cloud_mask_u8 S3 Path-Style DNS

- Date: 2026-07-14
- Status: blocked before dataset acquisition
- Candidate dataset: NOAA GOES-R ABI Level-2 Cloud Mask
- Attempted listing host: `https://s3.amazonaws.com/noaa-goes16`
- Failure class: dns_resolution_failed

## What Happened

After virtual-hosted S3 DNS failed for `noaa-goes16.s3.amazonaws.com`, the
downloader was changed to path-style S3 URLs:

```text
https://s3.amazonaws.com/noaa-goes16?list-type=2&prefix=ABI-L2-ACMF/2024/001/00/
```

The retry still failed before acquisition. Every configured prefix produced:

```text
listing_failed:<urlopen error [Errno -2] Name or service not known>
```

No S3 keys were listed and no NetCDF payloads were downloaded.

## Decision

Do not spend more attempts on GOES S3 from this environment. Retry only if DNS
resolution for `s3.amazonaws.com` works, or provide exact NetCDF URLs through a
different reachable mirror.
