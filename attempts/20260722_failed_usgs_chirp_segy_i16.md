# Failed: usgs_chirp_segy_i16 — no SEG-Y payloads

- Date: 2026-07-22
- Candidate: `staging/usgs_chirp_segy_i16`
- Domain: marine chirp sub-bottom seismic, int16 SEG-Y format 3 traces

## Attempt

User ran `bash staging/usgs_chirp_segy_i16/download.sh` on 2026-07-22.

Log: `.data/logs/usgs_chirp_segy_i16/download.latest.log`

```
skip oversized file length=18567615005 url=https://coastal.er.usgs.gov/data-release/doi-P1NZ6CC2/data/2024-310-FA_segy.zip
downloaded bytes=4510149 file=2024-310-FA_nav.zip
downloaded bytes=147201547 file=2024-310-FA_seisimag.zip
downloaded_files=2
```

Contents:

- `2024-310-FA_nav.zip` → `*.csv` nav files, metadata txt/xml
- `2024-310-FA_seisimag.zip` → `*_env.gif` envelope images, not SEG-Y

Build log: `.data/logs/usgs_chirp_segy_i16/build.latest.log` → `no native 16-bit samples accepted`

## Reason

- Real SEG-Y archive `2024-310-FA_segy.zip` is 18.5 GB, skipped by default `MAX_FILE_BYTES=600MB` cap.
- Smaller zips discovered are GIF previews and navigation, not `*.sgy`/`*.segy` with format code 3.
- Older DS seeds (311,259,553,590,620,526) returned no `.sgy` candidates via simple href scraping; may need deeper catalog parsing or ScienceBase direct links.

## Evidence

- Download manifest: `.data/downloads/usgs_chirp_segy_i16/download_manifest.json`
- Unzip -l shows GIFs, no .sgy
- 18.5 GB file skipped as oversized

## Classification

`transient_failure` / `needs_tooling` — needs exact small SEG-Y URL list or larger file cap with bounded extraction.

## Retry Condition

- Pin exact small SEG-Y files via `USGS_CHIRP_SEGY_URLS_FILE` with direct `*.sgy` links <600 MB, e.g., from DS 311/259 individual line files, or
- Increase `MAX_FILE_BYTES` to allow 18 GB zip but then bounded extraction of first few traces to stay under 1 GB primary cap, and update build to reject GIF zips.

## Value if Fixed

Would add marine sub-bottom profiling domain, distinct from earthquake waveforms.

