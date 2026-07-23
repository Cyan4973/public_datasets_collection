# Blocked: nasa_aviris_classic_hyperspectral_i16

- Date: 2026-07-22
- Candidate: `staging/nasa_aviris_classic_hyperspectral_i16`
- Domain: airborne imaging spectroscopy, 224-band

## Attempt

User ran `bash staging/nasa_aviris_classic_hyperspectral_i16/download.sh`

Log: `.data/logs/nasa_aviris_classic_hyperspectral_i16/download.latest.log`

```
no candidate URLs discovered; provide URL list or adjust seed selectors
```

Seed: `https://aviris.jpl.nasa.gov/data/free_data.html`

## Reason

The JPL free data page is a human HTML page listing scene names and links to sub-pages, not direct `*.hdr/*.img/*.bil` ENVI file URLs. The generic href scraper finds no files with suffixes `.tar .zip .hdr .img .bil`.

## Retry

Need direct ENVI URLs, e.g., from `https://aviris.jpl.nasa.gov/data/` holding `f970619t01p02_r02_sc02.a.rfl` etc., or from NASA DAAC with Earthdata auth, or provide exact `*.hdr` URLs via `AVIRIS_URLS_FILE`.

Parser `envi` (data type 2=int16,12=uint16) is sound.

