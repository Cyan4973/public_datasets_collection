# Cloudnet Lindenberg CHM15k raw attenuated backscatter (beta_raw) float32 development

## Outcome

Accepted `cloudnet_lindenberg_chm15k_beta_raw_f32`: native float32 non-screened attenuated backscatter profiles (`beta_raw`, sr-1 m-1) from the single DWD Lufft CHM15k ceilometer at the Lindenberg Meteorological Observatory (MOL-RAO), taken from ACTRIS Cloudnet daily `lidar` product files.

This is the corpus's first atmospheric-lidar family. Time × range active-echo matrices already exist (SHARAD radargram f32, aloft weather-radar bird profiles f32, echosounder water column at 8/16 bits). The novelty is therefore a new source, instrument class and physical quantity, not a new modality.

zlsim measured breadth OK. The nearest family is `gaia_dr3_astrometry_f32:gaia_pmra_masyr_f32` at distance 0.0516 with compression loss 0.02. Mode share is 0.0002 and there are no fill warnings.

## Source and rights

- Portal: ACTRIS Cloudnet data portal (cloudnet.fmi.fi, FMI). Files API `https://cloudnet.fmi.fi/api/files/<uuid>`; downloads from `https://cloudnet.fmi.fi/api/download/product/<uuid>/<YYYYMMDD>_lindenberg_chm15k_cdf99c53.nc`.
- Instrument: Cloudnet uuid `cdf99c53-6bd0-4146-be2a-604cf1164c30`, PID `https://hdl.handle.net/21.12132/3.cdf99c536bd04146`, serial CHM100110, owner German Meteorological Service (DWD).
- Selection: from the 366 Lindenberg CHM15k lidar files of 2024, the 1st and 15th of each month. All 24 are errorLevel `pass` with coverage ≥ 0.99, CloudnetPy 1.75.0 and cloudnet-processing 2.54.18; no substitution was needed.
- Pins: per-file uuid, filename, size, SHA-256 and CloudnetPy version are in `sources.tsv`, which is itself SHA-256-pinned (`3a8c2f03…`) in `scripts/chm15k.py`. The download is 919,628,874 bytes.
- License: CC BY 4.0. The docs.cloudnet.fmi.fi License section says "Cloudnet data is licensed under a Creative Commons Attribution 4.0 international licence", with no listed exceptions. Keep the Cloudnet/ACTRIS/DWD attribution and the per-file PIDs.

## Shape and conversion

Each natural record is one site-day Cloudnet lidar NetCDF4/HDF5 file. Each sample is that file's complete `beta_raw` matrix:

- time × 1535 range gates, time-major;
- one profile every 15 s;
- gates 9.99 m apart, from 9.99 m to 15,334.65 m.

`beta_raw` is IEEE float32 LE. Full days are chunked (2880, 768); each chunk is byte-shuffled (element size 4) and then deflated at level 4.

The pure-stdlib reader `h5lite.py` is copied unchanged from the accepted STOFS recipe and checks the lookup3 checksum of every metadata block. Decoding takes the chunk addresses from the v1 B-tree, inflates and unshuffles each chunk, and places its in-bounds rows. Values are written unchanged, with no scaling, masking, gap filling or reordering. The SNR-screened `beta` and `beta_smooth` variables are not emitted.

Missing-value policy:

- Gaps shorten the time axis; 5700–5800 rows are required.
- The netCDF default fill (0x7CF00000) is kept in place and counted. More than 1% fill is fatal.
- NaN, infinity, or any non-fill |v| > 1 is fatal.

## Accepted output

- Primary samples: 24.
- Shapes: 23 days of 5760 × 1535. 2024-03-01 is 5720 × 1535 because of one 625 s gap.
- Primary values: 212,137,000.
- Primary bytes: 848,548,000.
- Median sample: 8,841,600 values (35,366,400 bytes).
- Fill, NaN or infinite values: 0.
- Negative-value fraction per sample: 0.379–0.483.
- Sample maxima: 1.528e-4 to 1.101e-2. Sample minima: −3.8e-5 to −5.1e-4.
- Distinct values per stride-8 subsample of about 1.1M: about 1.09M–1.10M.
- Range axis: byte-identical across all 24 files.

## Judge checks

- `python3 tools/autocollect/gate.py staging/cloudnet_lindenberg_chm15k_beta_raw_f32`: PASS, no warnings.
- **verify.sh:** re-ran `bash staging/.../verify.sh` (2026-10-09 00:04:53 to 00:06:01); `verify ok samples=24 values=212137000 bytes=848548000`. Verify decodes by a different route from build: leaf sibling chain, streamed inflate and lane-zip unshuffle. It compares bytes and recomputes stats, index rows and manifest totals.
- **Local only:** `build.sh` and `verify.sh` make no network calls. The download log has 24 `meta ok` and 24 `file ok` lines.
- **Reader provenance:** `h5lite.py` is byte-identical (`cmp`) to the accepted STOFS recipe's copy.
- **Byte inspection (stdlib `array`/`struct`)** of 2024-01-01, 2024-07-15 and 2024-12-01:
  - noise std grows with range, as range correction predicts;
  - gates 10–200 are almost entirely positive (near-surface aerosol);
  - gates 1000–1535 are symmetric noise around zero;
  - 24–27 distinct exponents occur;
  - lane entropies are 8.00/8.00/7.97/≈3.2 bits;
  - mantissa trailing zeros fall off geometrically, so the float32 is full precision and not widened;
  - there are no duplicate profiles.
- **Seam check:** gate std is smooth across chunk boundary 767/768, and row correlations at the time-chunk seam match those elsewhere, so no chunk is misplaced.
- **Semantic decode check:** on 2024-07-15, the file's own SNR-screened `beta` (82.4% masked) equals the emitted `beta_raw` exactly at all 519,270 unmasked points checked.
- **Homogeneity:**
  - `calibration_factor` = 4e-12, `wavelength` = 1064 nm and `zenith_angle` = 5° in all 24 files, read from the contiguous scalars;
  - global attributes pin serial, instrument PID, file uuid and date;
  - the median time step is 15 s in every file.
- **Rights:**
  - docs.cloudnet.fmi.fi License section confirmed (CC BY 4.0 for Cloudnet data, no exceptions);
  - the live API record shows errorLevel pass, not tombstoned, not volatile;
  - no credentials in any script; no personal data.
- **Novelty:**
  - `novelty.py --url https://cloudnet.fmi.fi` matched only this staging recipe; terms cloudnet, ceilometer, chm15k, beta_raw, actris and aerosol matched nothing else;
  - `--type/--instrument/--archive` returned 0/0/0;
  - the vocabulary shows existing radargram and water-column echo-profile families, hence `new_source`.
- **Volume:** 849 MB is heavy against the roughly 100 MB downstream guideline. It is justified because each natural record is a 35 MB day, and more than about 28 days would breach the 1 GB cap. The extraction ratio is about 0.92, and the size is within accepted precedent (805 MB and 955 MB families). Coverage is one site and one year, and that is stated honestly.
