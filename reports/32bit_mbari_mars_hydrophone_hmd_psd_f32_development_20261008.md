# MBARI MARS hydrophone hybrid-millidecade PSD float32 development

## Outcome

Accepted `mbari_mars_hydrophone_hmd_psd_f32`.

Each sample is the calibrated underwater sound pressure spectral density for one day. It comes from the MBARI MARS cabled-observatory hydrophone (Monterey Bay, 36.7128 N 122.186 W, 891 m, 1 m above the seafloor).

- Stored by the publisher as native little-endian IEEE float32.
- 1440 one-minute spectra × 2787 hybrid millidecade bands (10 Hz – 99.9 kHz) per UTC day.
- Unit: dB re 1 µPa²/Hz.

This is the corpus's first ocean passive-acoustic or soundscape spectral family at any width. Time × frequency spectral-density matrices already exist for other quantities, such as NDBC ocean-wave spectra (f64) and the RSTN solar radio dynamic spectra (u8). The novelty is therefore recorded as `new_quantity`. The driver's zlsim measurement is `OK`: the nearest family is downstream `era5_temperature_pressure_levels_f32`, at distance 0.0582 with compression loss 0.0337.

## Source and rights

- Source: public anonymous S3 bucket `pacific-sound-spectra` (us-west-2), published by MBARI. Keys are `YYYY/MARS_YYYYMMDD.nc` (NetCDF4/HDF5, 16,124,324 B each).
- Product: "Hybrid Millidecade Band Sound Pressure Levels Computed at 1 Minute Resolution from Oceanic Passive Acoustic Monitoring Recordings at the MARS Cabled Observatory".
  - Creator: John Ryan, MBARI.
  - Method: PyPAM v0.2.0, following Martin et al. 2021a,b and ISO 18405 3.1.3.13.
  - Inputs: 1 Hz-resolution PSD from 1 s Hann/50%-overlap FFTs, averaged per minute, converted to HMB bands, then calibrated with the manufacturer's sensitivity.
- Instrument: Ocean Sonics icListen HF RB9-900m SN 1689 with a Reson TC4059-1 element.
- License: CC BY 4.0. Every file's global attributes state: "As for the original recordings available online (https://registry.opendata.aws/pacific-sound/), this derived data product carries the CC-BY 4.0 license." `download.sh` rejects any file lacking this sentence.
- The AWS Open Data registry entry `pacific-sound.yaml` declares `License: CC-BY 4.0`. Its Resources list names only the audio and model buckets, so the in-file statement by the producer is the primary grant for these exact objects.
- Attribution: MBARI. MARS was funded by NSF; SoundCoop by NOAA IOOS, BOEM, US Navy LMR and ONR.

## Shape and conversion

- Natural record: one daily file's root-group `psd` variable, a 1440 × 2787 matrix (minutes × bands, row-major).
- `scripts/mars_hdf5.py` is a pure-stdlib parser.
  - It reads the superblock and the root group's v2 object header, verifying lookup3 checksums including OCHK continuations.
  - It resolves the `psd` link by name.
  - It requires H5T_IEEE_F32LE, dataspace 1440 × 2787, and a v3 contiguous layout of exactly 16,053,120 B with no filter pipeline.
- The span at the layout address (37,004 in all 36 files, read per file) is copied verbatim. There is no rescaling, reordering or widening.
- NaN is the dataset fill value and is preserved natively. More than 10% NaN in a day, or any infinity, is fatal.
- Day selection, by `scripts/discover.py` and pinned in `days.tsv` (key, size, S3 multipart ETag, LastModified):
  - Start from the 2,189 MARS daily files of this exact layout (2017-06-14 .. 2023-08-01).
  - Take 36 evenly spaced positions.
  - Step each to the nearest day with 60 s of input audio in all 1440 minutes. Five positions moved by one day.
- Excluded: `mb05/`, `MANTA_961/`, `MBARI/`, `.jpg` quick-looks, and the 2015–2016 root-level files.
- `time`, `frequency`, `effort` and `sensitivity` are used only for validation and selection.

## Accepted output

| Item | Value |
|---|---|
| Source files downloaded | 36 × 16,124,324 B = 580,475,664 B |
| Primary samples | 36 (one per day; 2017: 3, 2018: 6, 2019: 6, 2020: 6, 2021: 6, 2022: 6, 2023: 3) |
| Values per sample | 4,013,280 (1440 × 2787) |
| Bytes per sample | 16,053,120 |
| Primary values | 144,478,080 |
| Primary bytes | 577,912,320 (99.56% of download) |
| NaN | 0 |
| Value range | 33.94 – 148.51 dB re 1 µPa²/Hz |

Per-day maxima are 102.6 – 148.5 dB, from brief 10 Hz transients. The README says 105 – 148 dB, which is a minor documentation nit.

- Aggregate sample SHA-256: `7f00e485104430407ea1127eec2642e72632da7939164069e90214176cb5764c`
- Build and independent verify both succeeded against the pinned local files.

## Judge checks

- **Gate:** `python3 tools/autocollect/gate.py staging/mbari_mars_hydrophone_hmd_psd_f32` → PASS, no warnings.
- **Verify:** I re-ran `bash staging/mbari_mars_hydrophone_hmd_psd_f32/verify.sh` and it passed on all 36 samples. Every day showed nan=0, dup_rows=0 and distinct=1.000.
- **Local-only build:** build.sh and the build/verify Python modules contain no network code. The driver's download log shows all 36 files validated against their pinned multipart ETags.
- **Byte identity:** my own script compared `file[37004:+16,053,120]` with the sample for 20171113, 20191130 and 20221228. All three were identical and matched the index SHA.
- **Bytes:**
  - In four samples (20170913, 20180521, 20210207, 20230702), all 256 low-byte values occur and the low 12 bits are zero in only about 0.02% of values. This is full float32 precision, not widened codes.
  - Distinct ratio is 0.74–0.77 per day. Equality with the previous minute or band is about 1e-5.
  - Medians are 44–55 dB. Low bands sit near 80 dB and bands above 25 kHz at the about 36 dB self-noise floor, which still varies with a per-column span of at least 1.5 dB. This is not fill.
- **Diversity:** all 36 sample SHA-256 hashes differ. The closest pair of daily mean spectra (20170715 vs 20210609) differs by 0.48 dB per band on average. Per-day broadband per-minute sd is 0.8–5.3 dB.
- **Homogeneity:** in all 36 files I confirmed an identical instrument string (SN 1689), identical sensitivity curve, identical frequency-axis hash, PyPAM 0.2.0 and the same psd unit string. The builder's summary mentions serial changes, but none appear in these files.
- **Rights:** I read the CC-BY 4.0 sentence from the file bytes and fetched `pacific-sound.yaml` ("License: CC-BY 4.0"). There are no credentials in any script and no personal data.
- **Novelty:**
  - `novelty.py --url https://pacific-sound-spectra.s3.amazonaws.com/` with terms millidecade, hydrophone, "pacific sound", MBARI, PyPAM, icListen, soundscape and "passive acoustic" matched only this candidate and an unrelated blocked 16-bit PCM stub.
  - `--type/--instrument/--archive` returned 0 matches.
  - There are no matches downstream. `spectral density` matches only NDBC wave spectra (f64), so the label is new_quantity rather than new_modality.
- **Volume:** 36 of 2,189 days, 578 MB. That is far above the ~100 MB downstream sub-sample, inside the 1 GB cap, with natural 16 MB records and no sharding.
