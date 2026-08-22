# NASA HEASARC NICER Detector Address Uint8

This staged recipe extracts three native unsigned-byte columns from the
photon-event tables of the already pinned June 2017 NASA NICER/XTI observation
selection:

- `RAWX`: detector focal-plane X address (`0..7` observed);
- `RAWY`: detector focal-plane Y address (`0..6` observed); and
- `DET_ID`: detector identifier (`0..67` observed, with hardware gaps).

Each complete observation/field sequence is one natural sample in photon-event
order. The three fields are FITS `TFORM=1B` scalars with identity scaling and
no null sentinel. FITS headers, row framing, other event columns, and gzip
bytes are excluded.

This deliberately reuses the exact source inventory and local download cache
of `nasa_heasarc_nicer_pi_i16`. It adds new detector-routing series, not new
astronomical observations. Its user-run download step validates the shared
cache and invokes the existing pinned downloader only when source files are
missing.

Run:

```bash
bash staging/nasa_heasarc_nicer_detector_u8/download.sh
bash staging/nasa_heasarc_nicer_detector_u8/build.sh
bash staging/nasa_heasarc_nicer_detector_u8/verify.sh
```
