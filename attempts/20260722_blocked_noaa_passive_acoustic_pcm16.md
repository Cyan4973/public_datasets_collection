# Blocked: noaa_passive_acoustic_pcm16

- Date: 2026-07-22
- Candidate: `staging/noaa_passive_acoustic_pcm16`
- Domain: marine bioacoustics, passive hydrophone monitoring
- Intended primary: `noaa_passive_acoustic_pcm16` int16 WAV PCM

## Attempt

User ran `bash staging/noaa_passive_acoustic_pcm16/download.sh` on 2026-07-22.

Log: `.data/logs/noaa_passive_acoustic_pcm16/download.latest.log`

```
no candidate URLs discovered; provide URL list or adjust seed selectors
```

Seed: `https://www.ncei.noaa.gov/products/passive-acoustic-data`

## Reason

The NCEI product landing page is a JS-rendered catalog, not a static HTML directory listing with direct `.wav` links. `bounded_url_download.py` scrapes `<a href>` and raw URLs, so it finds no `.wav/.zip` candidates.

## Retry Condition

Retry with direct data listing seeds, e.g.:

- `https://www.ncei.noaa.gov/data/passive-acoustic-data/` (S3-style directory indexes)
- `https://noaa-passive-acoustic-data.s3.amazonaws.com/` or `https://ncei-noaa-passiveacoustic.s3.amazonaws.com/` buckets
- Specific project pages like `https://www.ncei.noaa.gov/data/passive-acoustic-data/ncei/access/` that list per-deployment WAVs
- Or provide exact WAV URLs via `NOAA_PASSIVE_AUDIO_URLS_FILE`.

Parser `wav` is sound; only discovery needs fixing.

## Value if Fixed

Would add hydrophone bioacoustics domain, distinct from speech/music.

