# Fermi LAT weekly photon events float32 development

## Outcome

Accepted `fermi_lat_weekly_photon_events_f32`: native float32 per-photon reconstructed energy, sky direction and instrument-frame incidence angles. They come from the `EVENTS` tables of 18 Fermi Large Area Telescope weekly all-sky photon files (Pass 8 R3 SOURCE class, processing P305).

This family is distinct from the accepted HEASARC event-list recipes:

- `fermi_gbm_tte_nai_photon_arrival_times_f64` is a different instrument (GBM) and quantity (arrival times, f64).
- `nasa_heasarc_nicer_pi_i16` and `nasa_heasarc_nicer_detector_u8` hold integer X-ray energy-channel codes and detector addresses.

No float-valued per-photon energy or photon-direction family exists locally or downstream. The label is `new_quantity` within the known photon-event-list modality.

## Source and rights

- Source: `https://heasarc.gsfc.nasa.gov/FTP/fermi/data/lat/weekly/photon/lat_photon_weekly_wNNN_p305_v001.fits`.
  - The listing has 949 files (w009..w958, w512 absent).
  - The population is the 940 weeks w010..w950.
  - The 18 targets sit at index `floor((k + 0.5) * 940 / 18)`, giving w036, w088, w140, w192, w245, w297, w349, w401, w453, w506, w559, w611, w663, w716, w768, w820, w872 and w924. That is one week in early February of each year 2009-2026.
- Download: 18 files, 3,507,436,800 bytes, 35,784,618 photon rows.
- Pinning: HEASARC publishes no content hash. Each file is pinned in `sources.tsv` by:
  - exact Content-Length and Last-Modified;
  - EVENTS `NAXIS2` and `DATASUM`;
  - `TSTART`/`TSTOP` and the GTI row count.

  download.sh verifies the FITS `CHECKSUM` of all 54 HDUs and 54 `DATASUM`s, and records each file's SHA-256 in `download_inventory.json`. build.sh re-checks those hashes.
- License: `LicenseRef-NASA-SMD-Open-Data`. The FSSC data policy ("Last Updated: 28-Aug-2025") states: "Since the beginning of the second year of operations, all LAT science data has been released as early as possible ... The LAT public archive includes the science data acquired in the first year that was initially proprietary." The NASA SMD Scientific Information Policy states that SMD-funded information is made publicly available. This is the same basis as the accepted GBM TTE, NICER, BATSE and GRAIL recipes. download.sh re-checks the FSSC sentence.

## Shape and conversion

Each natural record is one weekly photon file. Per file, five scalar `E` (big-endian float32) columns of the 98-byte `EVENTS` row are copied bit-exact to little-endian, in stored (time) row order:

| series | column | unit | row offset |
|---|---|---|---|
| `lat_photon_energy_f32` | ENERGY | MeV | 0 |
| `lat_photon_ra_f32` | RA | deg | 4 |
| `lat_photon_dec_f32` | DEC | deg | 8 |
| `lat_photon_theta_f32` | THETA | deg | 20 |
| `lat_photon_phi_f32` | PHI | deg | 24 |

The schema is fully validated:

- 23 TTYPE/TFORM pairs with TFORM-derived offsets;
- TUNITs;
- no TSCAL/TZERO/TNULL/TDIM;
- `PASS_VER P8R3`;
- `DSTYP2 BIT_MASK(EVENT_CLASS,128,P8R3)`.

Build also confirms row alignment: every TIME lies inside TSTART..TSTOP with 0 backsteps, and every row has the SOURCE bit. Not emitted:

- L/B (a fixed rotation of RA/DEC);
- ZENITH_ANGLE and EARTH_AZIMUTH_ANGLE;
- TIME and LIVETIME (f64);
- EVENT_ID and RUN_ID;
- versions, bit arrays and CONVERSION_TYPE;
- the all-zero DIFRSP0-4 columns;
- GTI.

## Accepted output

- Primary samples: 90 (18 per series)
- Primary values: 178,923,090 (35,784,618 per series)
- Primary bytes: 715,692,360 (143,138,472 per series)
- Sample size: 605,624 (w036) to 3,260,127 (w297) values; median 1,982,040.5
- Realized ranges:
  - ENERGY 7.666 MeV to 3,489,360 MeV
  - RA 3.1e-6 to 360.0 deg
  - DEC -89.989 to 89.991 deg
  - THETA 0.0046 to 83.54 deg
  - PHI 5.3e-6 to 360.0 deg
- Distinct-value fraction per sample: 0.83-0.99. All 90 sample SHA-256 values are unique.
- Breadth (zlsim, 2026-10-08 20:06): verdict OK. THETA is the only non-redundant series: nearest d 0.0484, best near-family loss 4.5%. ENERGY (~ SHARAD radargram, d 0.042), RA (~ rat fUS, d 0.027), DEC (~ CMS jet_eta, d 0.046) and PHI (~ rat fUS, d 0.026) each meet the redundancy thresholds individually. They are high-entropy measured floats: zlib about 1.1x, own OpenZL ratio 1.24-1.37.

The local build and the independent byte-for-byte verification both completed against the pinned files.

## Judge checks

- `python3 tools/autocollect/gate.py staging/fermi_lat_weekly_photon_events_f32`: PASS, no warnings.
- Ran `bash staging/fermi_lat_weekly_photon_events_f32/verify.sh` myself: `verify ok samples=90 primary_bytes=715692360`. Confirmed that build.sh reads only `$DATA_ROOT/downloads/...` and re-checks the inventory SHA-256 values.
- Read all four scripts. verify_events.py shares no code with lat_events.py: its own mmap card parser, its own DATASUM, and struct.iter_unpack decoding.
- Wrote my own stdlib FITS walker plus a `struct '>9fd'` row decoder (/tmp/autocollect/fermi_lat_weekly_photon_events_f32/scripts/spot.py). On w036, w611 and w924 it checked 200 random rows plus the first and last row per week, all five fields, against the samples: 0 mismatches. EVENTS header confirmed: TTYPE/TFORM/TUNIT, DSTYP2 SOURCE-class mask, PASS_VER P8R3.
- Value inspection over 20 samples (4 weeks × 5 fields):
  - Quantiles are physically sensible.
  - The low-mantissa-byte-zero fraction is about 1/256, so the floats are unquantized.
  - Top repeat counts are 3-9 and consecutive duplicates 0-3, so nothing is degenerate.
  - RA w297's lower distinct fraction (0.855) matches the 2014 Galactic-center-biased survey (photon pile-up near RA 266°, ulp about 3e-5).
- Rights: opened the FSSC policy page and the NASA SMD policy page myself. The LAT open-release sentence is present (also in the local fetched copy). The basis is consistent with four accepted NASA recipes. No credentials; no personal data.
- Novelty: `novelty.py --url` / `--terms` / `--vocabulary` / `--type photon_event_attributes --instrument fermi_lat --archive heasarc.gsfc.nasa.gov/FTP/fermi/data/lat/weekly` found no LAT line or archive; same-type entries are only NICER i16/u8 integer codes. I read the per-series zlsim JSON. Partial redundancy is permitted by the calibration policy, with precedent in `grail_lgrs_kbr1c_ka_band_ranging_f64`, accepted with 1 of 3 series redundant. Here it is 4 of 5, recorded above so downstream selection can weigh it.
- Volume: 18 weeks out of 940, bounded by the 5 GB per-candidate download cap at about 195 MB per week. Whole natural weekly files, not sharded; 716 MB is under the 1 GB cap.
- Cosmetic, not blocking: the README says "36 DATASUMs", but 54 are verified because the PRIMARY HDU also carries one.
