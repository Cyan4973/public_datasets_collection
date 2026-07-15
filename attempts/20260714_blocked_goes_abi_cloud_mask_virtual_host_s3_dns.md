# goes_abi_cloud_mask_u8 Virtual-Hosted S3 DNS

- Date: 2026-07-14
- Status: blocked URL form
- Candidate dataset: NOAA GOES-R ABI Level-2 Cloud Mask
- Attempted listing host: `https://noaa-goes16.s3.amazonaws.com`
- Failure class: dns_resolution_failed

## What Happened

The first GOES downloader failed immediately while listing the public S3 prefix:

```text
ABI-L2-ACMF/2024/001/00/
```

Python raised:

```text
socket.gaierror: [Errno -2] Name or service not known
```

for `noaa-goes16.s3.amazonaws.com`.

## Decision

Switch the default downloader to S3 path-style URLs:

```text
https://s3.amazonaws.com/noaa-goes16
```

and record listing failures in `download_failures.tsv` instead of failing with
a traceback.
