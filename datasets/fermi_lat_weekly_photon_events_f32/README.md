# Fermi LAT Weekly All-Sky Photon Events (float32)

`fermi_lat_weekly_photon_events_f32` collects native float32 per-photon
quantities from the Fermi Large Area Telescope (LAT) weekly all-sky photon
files. Each weekly file holds one week of SOURCE-class gamma-ray photons
(Pass 8 R3, processing P305). For 18 weeks, one in early February of each
year 2009–2026, five `EVENTS` columns are emitted. Each column is copied bit-exact as
little-endian float32, in stored row order:

| series | column | unit | meaning |
| --- | --- | --- | --- |
| `lat_photon_energy_f32` | `ENERGY` (row bytes 0–3) | MeV | reconstructed photon energy |
| `lat_photon_ra_f32` | `RA` (4–7) | deg | right ascension J2000 of the reconstructed direction |
| `lat_photon_dec_f32` | `DEC` (8–11) | deg | declination J2000 |
| `lat_photon_theta_f32` | `THETA` (20–23) | deg | off-axis (inclination) angle in instrument frame |
| `lat_photon_phi_f32` | `PHI` (24–27) | deg | azimuth in instrument frame |

This gives one sample per week per field: 18 × 5 = 90 samples. From the pinned
headers that is 35,784,618 photons per field, 143,138,472 bytes per series and
715,692,360 bytes in total.

## Source

`https://heasarc.gsfc.nasa.gov/FTP/fermi/data/lat/weekly/photon/` lists 949
files `lat_photon_weekly_wNNN_p305_v001.fits` (w009–w958; w512 is absent, the
March 2018 safe-mode week; w958 is the growing current week). Each file is
FITS with three HDUs:

- `PRIMARY` (no data)
- `EVENTS`: binary table, `NAXIS1 = 98`, 23 columns. `ENERGY`, `RA`, `DEC`,
  `L`, `B`, `THETA`, `PHI`, `ZENITH_ANGLE` and `EARTH_AZIMUTH_ANGLE` are
  `E`; `TIME` is `D`. The rest are `EVENT_ID`/`RUN_ID` (`J`), versions,
  `EVENT_CLASS`/`EVENT_TYPE` (`32X`), `CONVERSION_TYPE`, `LIVETIME` and
  `DIFRSP0-4`.
- `GTI` (START/STOP doubles)

The `EVENTS` data-subspace keywords declare the selection
`BIT_MASK(EVENT_CLASS,128,P8R3)`, i.e. SOURCE class. Every HDU carries a FITS
`CHECKSUM`; `EVENTS` and `GTI` also carry `DATASUM`.

The anonymous `nasa-heasarc` S3 mirror only reaches w871, so the recipe uses
the HEASARC host directly. It supports byte ranges, but serves no content
hash.

## Selection

`discover.sh` (documentation, not part of the download contract) fetches the
listing and runs `scripts/select_weeks.py`:

- **Population**: the 940 listed weeks w010–w950. w009 is the partial first
  week. Weeks after w950 are excluded because the newest files are still
  being regenerated.
- **Targets**: index `floor((k + 0.5) * 940 / 18)`, k = 0..17. This lands on
  one week in early February of every year:
  w036, w088, w140, w192, w245, w297, w349, w401, w453, w506, w559, w611,
  w663, w716, w768, w820, w872, w924.
- **N = 18, not the screener's 20**: 20 weeks would need 4.22 GB of downloads
  plus 0.86 GB of output, over the pipeline's 5 GB per-candidate cap. 18 weeks
  need 3.51 GB plus 0.72 GB.
- **Probes** per file: HEAD (Content-Length, Last-Modified), a 28,800-byte
  prefix range GET (primary and `EVENTS` headers) and a 28,800-byte suffix
  range GET (`GTI` header). The pinned size must equal the FITS layout exactly
  (headers + padded 98 × NAXIS2 + GTI). `sources.tsv` pins:
  - file name, bytes and Last-Modified;
  - `NAXIS2`, `EVENTS` `DATASUM`, `TSTART`/`TSTOP`, `DATE-OBS`/`DATE-END`;
  - the GTI row count and the population/target indices.

Pinned rows per week range from 605,624 (w036) to 3,260,127 (w297).

## Download, build, verify

```bash
bash staging/fermi_lat_weekly_photon_events_f32/download.sh   # ~3.51 GB, 18 files
bash staging/fermi_lat_weekly_photon_events_f32/build.sh
bash staging/fermi_lat_weekly_photon_events_f32/verify.sh
```

All three honour `DATA_DIR` (default `.data`) and log to
`$DATA_DIR/logs/fermi_lat_weekly_photon_events_f32/`.

- **download.sh** uses resumable curl (`-C -`, `--speed-limit 1024
  --speed-time 120`, `--max-filesize`, no `--max-time` on payloads) into
  `.part` files. It renames a file only after `scripts/validate_download.py`
  accepts it:
  - exact size;
  - HDU sequence and primary identity (GLAST/LAT, `PROC_VER 305`);
  - the full 23-column schema with TFORM-derived offsets, `TUNIT`s, no
    `TSCAL`/`TZERO`/`TNULL`, `PASS_VER P8R3` and the SOURCE-class DSS
    keywords;
  - every `CHECKSUM` and `DATASUM`, zero padding, no trailing bytes;
  - the pinned `NAXIS2`, `DATASUM`, `TSTART`, `TSTOP` and GTI rows.

  A part that fails validation is refetched once from scratch, since weekly
  files are occasionally regenerated upstream. `download_inventory.json`
  records each file's SHA-256. The FSSC policy page is fetched as soft
  provenance, and the run fails if it no longer states the LAT open-release
  sentence.
- **build.sh** (`scripts/lat_events.py`) re-walks each file and streams
  `EVENTS` in row-aligned chunks. Each field is copied with strided slices
  that also byte-swap. It requires:
  - finite values inside the physical ranges (ENERGY 0..1e7 MeV, RA 0..360,
    DEC −90..90, THETA 0..180, PHI 0..360);
  - the SOURCE bit on every row's `EVENT_CLASS`, and every `TIME` inside
    `TSTART..TSTOP` (row-alignment checks; neither is emitted);
  - at least 1,000 distinct values and min < max per sample, and unique
    outputs.

  It writes `index/<id>/samples.jsonl` with the standard fields plus week,
  dates, MET window, min/max (from the stored float32), distinct count,
  first value and SHA-256.
- **verify.sh** (`scripts/verify_events.py`) is an independent
  implementation. It has its own card parser over `mmap` and its own `EVENTS`
  `DATASUM`, and decodes with `struct.iter_unpack` using a row format built
  from the TFORM offsets. It then checks:
  - byte equality with every sample;
  - ranges and degeneracy;
  - every index statistic, the exact inventory and the manifest totals.

### Self-tests (before download)

- The checksum code verified the real `CHECKSUM`/`DATASUM` of all 18 GTI
  HDUs and 18 primary HDUs captured by the probes.
- On the 88 real rows in each prefix probe, slice extraction matched
  `struct` decoding. ENERGY was positive, TIME was sorted and inside the
  window, and the SOURCE bit was set.
- Synthetic files were built from the real headers with ~110k random rows
  and freshly encoded `CHECKSUM`/`DATASUM`. They passed validate, build and
  the independent verify, and matched a per-row `struct` spot check
  byte-for-byte.
- The build rejected a flipped data byte (DATASUM), a NaN energy, an
  out-of-range DEC and a row without the SOURCE bit. The verifier rejected
  a tampered sample.

## Homogeneity

All samples come from one instrument (LAT), one event reconstruction and
selection (P8R3 SOURCE), one processing (P305) and one fixed column layout.
Each series is one quantity in one unit. The five series are different
columns of the same photon records and are never mixed in a sample.
Natural variation:

- **Photon count per week**: early-mission weeks (before the late-2009
  change of the survey rocking angle) hold roughly a third as many photons:
  w036 has 605,624 rows, against 1.5–3.3 M later. To our understanding this
  is because the larger rocking angle brings more Earth-limb photons into
  the field of view. The product and columns are unchanged.
- **Content**: RA/DEC follow the sky survey, with the Galactic plane and
  bright sources. THETA/PHI follow the instrument pointing. ENERGY follows a
  steep power law (realized 7.7 MeV to 3.49 TeV).

The 18 weeks fall at the same time of year, so the orbital-precession and
sky-scan phase are not systematically sampled. That is a side effect of
even spacing, not a choice.

## What is not emitted

- `L`, `B`: Galactic coordinates, a fixed rotation of RA/DEC.
- `ZENITH_ANGLE`, `EARTH_AZIMUTH_ANGLE`: Earth-frame transforms of the
  direction.
- `TIME`: f64.
- `EVENT_ID`, `RUN_ID`: ids.
- Versions, `EVENT_CLASS`/`EVENT_TYPE` bit arrays, `CONVERSION_TYPE`: codes.
- `LIVETIME`: f64.
- `DIFRSP0-4`: all-zero placeholders; the DIFRSP labels are `NONE`.
- `GTI`.

## Novelty

`tools/autocollect/novelty.py --url .../lat/weekly/photon/ --terms 'fermi lat'
lat_photon 'photon energy' gamma-ray` finds no recipe, registry, ledger or
downstream match beyond the shared host. The nearest relatives:

- `fermi_gbm_tte_nai_photon_arrival_times_f64`: a different instrument (GBM)
  and quantity (arrival time, f64).
- `nasa_heasarc_nicer_pi_i16`: X-ray energy *channel* codes, int16.
- `magic_gamma_telescope_event_features_f64`: simulated Cherenkov image
  features, f64.

No float32 photon-energy or photon-direction family exists locally or
downstream. HEASARC already backs several accepted recipes (NICER ×2, BATSE,
GBM, SDO), so the same-host concentration is a known caveat.

## License

NASA SMD Open Scientific Data Policy (`LicenseRef-NASA-SMD-Open-Data`). The
FSSC data policy was re-read on 2026-10-08 ("Last Updated: 28-Aug-2025"):
"Since the beginning of the second year of operations, all LAT science data
has been released as early as possible, typically within a day or two of
acquisition. The LAT public archive includes the science data acquired in the
first year that was initially proprietary."

This is the same basis as the accepted HEASARC recipes. Citation: Atwood et
al. 2009, ApJ 697, 1071, plus HEASARC/FSSC acknowledgement.

## Realized output

- 90 samples (18 per series), 178,923,090 float32 values, 715,692,360 bytes.
  Median 1,982,040.5 values per sample; range 605,624 (w036) to 3,260,127
  (w297).
- Ranges:
  - ENERGY 7.666 MeV to 3.489e6 MeV
  - RA 3.1e-6 to 360.0 deg
  - DEC −89.989 to 89.991 deg
  - THETA 0.0046 to 83.54 deg
  - PHI 5.3e-6 to 360.0 deg
- Distinct-value fraction per sample: 0.83–0.99.
- In every file, TIME is non-decreasing and every row has the SOURCE bit.
- All 54 HDU CHECKSUMs and 36 DATASUMs verify. Every sample SHA-256 is
  unique.
- Generic compressibility on the first 4 MB of w036 and w506 is low:
  - ENERGY: zlib-9 1.10–1.11×, xz-6 1.11×
  - RA: zlib-9 1.14–1.15×, xz-6 1.21–1.23×
  - DEC: zlib-9 1.09–1.13×, xz-6 1.11–1.18×
  - THETA: zlib-9 1.13–1.17×, xz-6 1.17–1.25×
  - PHI: zlib-9 1.12–1.14×, xz-6 1.16–1.18×

  These are high-entropy measured float32 values, rows in time order with
  no smooth structure within a column.

## Caveats

- **No published content hash.** Integrity rests on the FITS checksums plus
  the pinned size, `NAXIS2`, `DATASUM` and window. A regenerated upstream file
  fails the pins and needs re-running `discover.sh`.
- **RA/DEC/PHI may compress poorly.** They are close to noise-like floats on
  short scales. ENERGY and THETA are more structured.
- **Size.** Primary output is ~716 MB, well above the ~100 MB that
  downstream subsamples. That follows from taking whole weekly files at
  their natural boundary (no sharding).
