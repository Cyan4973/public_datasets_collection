# mbari_mars_hydrophone_hmd_psd_f32

Calibrated deep-sea underwater sound pressure spectral density from the MBARI
MARS cabled-observatory hydrophone (Monterey Bay, 891 m), as published by MBARI
in the public `pacific-sound-spectra` S3 bucket: one NetCDF4 file per UTC day
holding a `psd` variable of 1440 one-minute spectra x 2787 hybrid millidecade
bands (10 Hz - 99.9 kHz), float32, dB re 1 uPa^2/Hz, computed with PyPAM v0.2.0
following Martin et al. (2021) / SoundCoop.

## Scope

- 36 days, evenly spread over the 2,189 MARS daily files of the standard
  16,124,324 B layout (2017-06-14 .. 2023-08-01), each with full input effort
  (60 s of audio in all 1440 minutes). Pinned in `days.tsv` (key, size, S3
  multipart ETag, LastModified).
- One sample per day = the complete `psd` matrix: 4,013,280 float32 values,
  16,053,120 B. Total 36 samples, 577,912,320 B primary.
- Download: 36 x 16,124,324 = 580,475,664 B (whole files; the psd span is
  99.56% of each file, and whole files allow checking the pinned ETag).
- Excluded: `mb05/` (other site/recorder, different band count), `MANTA_961/`,
  `MBARI/` comparison folders, `.jpg` quick-looks, root-level 2015-2016 files.

## License

CC BY 4.0. Each file's global attributes say: "As for the original recordings
available online (https://registry.opendata.aws/pacific-sound/), this derived
data product carries the CC-BY 4.0 license." `download.sh` rejects files
without that sentence. The AWS Open Data registry entry for Pacific Sound
declares `License: CC-BY 4.0` (its Resources list names the audio and model
buckets, not the spectra bucket). Attribution: MBARI (creator John Ryan); MARS
funded by NSF; SoundCoop funded by NOAA IOOS, BOEM, US Navy LMR, and ONR.

## Pipeline

- `discover.sh` / `scripts/discover.py` (documentation only): listing plus
  ~80 KB of header and tail range reads per probed day; regenerates `days.tsv`.
- `download.sh`: one-byte liveness check, then a resumable curl
  (`-C -`, stall-based abort) per pinned key; `scripts/validate_download.py`
  checks the exact size, the multipart ETag (MD5 of 8 MiB part MD5s), the
  embedded title, site and license text, the HDF5 structure, and that the
  `time` axis is exactly the 1440 minutes of the file's date.
- `build.sh` / `scripts/mars_psd.py build`: `scripts/mars_hdf5.py` parses the
  superblock and the root-group v2 object header (lookup3 checksums, OCHK
  continuations), resolves the `psd` link by name, and requires
  H5T_IEEE_F32LE, dataspace 1440 x 2787, and a v3 contiguous layout of exactly
  16,053,120 B with no filter pipeline (chunked or compressed variants are
  fatal). The span at the layout address (37,004 in every pinned file; read
  per file, never hardcoded) is copied verbatim to
  `samples/<id>/mars_hmd_psd_db_f32/MARS_YYYYMMDD.bin`.
- `verify.sh`: re-parses every source, byte-compares the sample to the
  source span, recomputes statistics with a separate struct-based decoder,
  checks the index rows and the manifest totals, and rejects infinities,
  >10% NaN, constant samples, more than 14 repeated consecutive minute
  spectra, and a mean per-minute distinct-value ratio below 0.5.

## Missing values

The psd fill value is NaN. NaN is preserved natively and counted per sample
(`nan_count` in `samples.jsonl`). Infinities or more than 10% NaN in a day are
fatal. Realized build (2026-10-08): 0 NaN across all 36 days, finite range
33.94 .. 148.51 dB (per-day maxima 105-148 dB; in the two days inspected the
maximum sits in the lowest band, 10 Hz, and only ~50-60 of 4.0 M values exceed
120 dB, i.e. brief low-frequency transients), 0 repeated consecutive minute spectra, per-minute
distinct-value ratio ~1.0; aggregate sample SHA-256
7f00e485104430407ea1127eec2642e72632da7939164069e90214176cb5764c.

## Notes

- This is a derived spectral product (log-domain dB levels), not raw pressure.
  It is the publisher's standard community data product. The raw 16 kHz WAVs
  are 24-bit PCM, so they are not 32-bit material.
- The auxiliary `time`, `frequency`, `effort` and `sensitivity` variables are
  used only for validation and selection; they are not emitted.
- Parser self-tests (run from /tmp during authoring): lookup3 matched its
  reference vectors; real-file header and tail parses validated every OHDR
  checksum; mutated headers (checksum flip, chunked layout, big-endian dtype,
  size change, shape change, renamed link) were all rejected; an end-to-end
  build and verify on a synthetic full-size file with NaN rows passed
  byte-for-byte.
