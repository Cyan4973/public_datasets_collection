# Transient Failure: sdss_corrected_frame_fits_i16 — 503

- Date: 2026-07-22
- Candidate: `staging/sdss_corrected_frame_fits_i16`
- Domain: optical sky survey CCD imaging, BITPIX=16

## Attempt

```
bash staging/sdss_corrected_frame_fits_i16/download.sh
```

Log: `.data/logs/sdss_corrected_frame_fits_i16/download.latest.log`

```
curl: (22) The requested URL returned error: 503
...
no SDSS frame files discovered
```

Seeds:
- https://data.sdss.org/sas/dr17/eboss/photoObj/frames/301/756/4/ etc.

## Reason

data.sdss.org returns HTTP 503 for directory listings. Previously deferred for same reason.

## Retry

Need exact stable direct frame URLs via `LOCAL_DIR` or pinned URL file, or alternative SDSS hosting (e.g., `https://dr12.sdss.org/`).

