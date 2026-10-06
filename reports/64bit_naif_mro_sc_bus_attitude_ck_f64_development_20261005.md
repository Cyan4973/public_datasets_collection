# MRO spacecraft-bus attitude (NAIF CK type 3) float64 development

## Outcome

Accepted `naif_mro_sc_bus_attitude_ck_f64`. It holds the reconstructed attitude of the Mars Reconnaissance Orbiter spacecraft bus, as stored by NAIF/JPL in weekly telemetry-based C-kernels in the NASA PDS MRO SPICE archive.

The family is distinct from the accepted `nasa_naif_de440s_spk_coefficients_f64`. That recipe also reads a NAIF DAF container, but its content is planetary-ephemeris Chebyshev coefficients from generic kernels. This recipe keeps two different quantities measured by spacecraft attitude control: the onboard Kalman-filter attitude quaternion and the IMU (ring-laser gyro) body rates.

## Source and rights

- Source: NASA PDS data set `MRO-M-SPICE-6-V1.0`, volume `MROSP_1000`, `data/ck/mro_sc_psp_*.bc`, served by NAIF at `https://naif.jpl.nasa.gov/pub/naif/pds/data/mro-m-spice-6-v1.0/mrosp_1000/data/ck/`.
- Fallback: the USGS Astrogeology anonymous S3 mirror `asc-isisdata`. Its segment arrays are byte-identical at word addresses shifted by 128 or 256; both address sets are pinned. The realized download did not use it.
- Kernels: 11, the first weekly bus CK of each year 2007-2017. For 2015 this is `mro_sc_psp_150106_150112_v2.bc`, per PDS errata; only that version is archived.
- Pins: object sizes, DAF word addresses, SCLK coverage, PDS label SHA-256 values and all 44 per-segment SHA-256 values, in `sources.tsv`.
- License: `LicenseRef-US-Government-Public-Domain`, the corpus label used for NAIF data (DE440s precedent). The operative grant is the NAIF rules page: "SPICE kernels placed on the NAIF server may be downloaded and used by anyone"; "Redistribution of SPICE kernels distributed by NAIF is permitted as long as they have not been modified"; commercial use needs "No fees or licensing". The NAIF CK aareadme says the weekly reconstructed files "are intended for OPS use and for archiving in PDS".

## Shape and conversion

Each natural record is one whole CK type-3 segment: the kernel's own DAF array, which MSOPCK writes with up to 100,000 pointing records. The 4 segments per kernel are at ordinals `floor(i*M/4)` over the kernel's M = 33-40 segments, so they spread across the week. Each segment covers 4.0-5.5 h of ACS telemetry at 5 or 10 Hz.

`download.sh` range-fetches only the DAF file record, the summary chain, the PDS label and the 44 exact segment byte ranges. It resumes by appending only the missing tail and accepts only 206 responses carrying the expected Content-Range. It validates structure and SHA-256 before renaming.

`build.sh` splits each segment into pointing words 1-4 (quaternion), words 5-7 (angular velocity) and the N encoded-SCLK tags. The words are byte-swapped from big-endian to little-endian float64 with no float arithmetic, renormalisation or re-signing. The epoch and interval directories and the (NINTS, N) trailer are bookkeeping and are not emitted.

Validation:
- every descriptor is instrument -74000, frame -74900 (`MRO_MME_OF_DATE`), type 3, av flag 1;
- segment length = 7N + N + floor((N-1)/100) + NINTS + floor((NINTS-1)/100) + 2;
- epochs are strictly increasing and inside the descriptor coverage;
- |q| is within 1e-6 of 1;
- all values are finite;
- the gyro-era rate-step guard is >= 2e-6 rad/s.

The window stops at 2017 because MRO moved to star-tracker-only ("all-stellar") attitude determination in 2018. After that the stored rates are 6-100x smoother and form a different generation process.

## Accepted output

| series | role | samples | values | bytes |
|---|---|---|---|---|
| `mro_sc_bus_quaternion_f64` | primary | 44 | 17,600,000 | 140,800,000 |
| `mro_sc_bus_angular_rate_f64` | primary | 44 | 13,200,000 | 105,600,000 |
| `mro_sc_bus_sclk_epoch_ticks_f64` | auxiliary | 44 | 4,400,000 | 35,200,000 |

- Primary samples: 88; primary values: 30,800,000; primary bytes: 246,400,000.
- Sample shapes: 100,000 x 4 (quaternion) and 100,000 x 3 (rate). Median primary sample: 350,000 values.
- Download: 282,023,537 B (281,952,704 B of segment words plus 59,209 B of DAF records, HTTP headers and labels), all from the PDS host.
- Ranges:
  - quaternion components -0.99975 to 0.99974;
  - rate components -1.654e-3 to 1.655e-3 rad/s;
  - median |w| 9.4e-4 rad/s, MRO's orbital rate;
  - max |q|-1 per segment 7.2e-9 to 9.6e-9;
  - per-segment rate-step medians 7.9e-6 to 1.2e-5 rad/s on every axis.
- Character: quaternions are 8-decimal telemetry values (100% exact at 8 decimals, not float32-representable), with xz about 0.55. Rates are full double precision, with xz about 0.85.

## Judge checks

- `python3 tools/autocollect/gate.py staging/naif_mro_sc_bus_attitude_ck_f64`: PASS, no warnings.
- Ran `verify.sh` myself: 44 segments re-decoded with an independent struct reader. Byte equality, index min/max, manifest counts and segment SHA-256 pins all passed.
- Byte inspection with stdlib `struct` on 5 samples spread over 2007-2017:
  - 97.8k-99.9k distinct values per quaternion component out of 100k;
  - zero consecutive duplicate records and zero hemisphere flips;
  - epoch steps of about 51.2 ticks (0.2 s), with 10 Hz stretches;
  - all 44 samples unique per series.
- Rates are independent of the quaternions:
  - Numerically, finite-difference ω from consecutive quaternions, expressed in the base frame, matches the stored av to a median residual of 1.8e-5 against |av| of 9.3e-4. Rates made up from 1e-8-quantized quaternions would agree to about 2e-7.
  - In the source, a 16 KB range probe of the 2010 kernel's comment area shows `ANGULAR_RATE_PRESENT = 'YES'` and NAIF's note that IMU rates lead the quaternions by a small unknown offset.
- Rights: fetched the NAIF rules page and the CK `aareadme.txt` and confirmed the quotes verbatim. The pinned PDS label shows PRODUCER_ID NAIF/JPL and PRODUCT_VERSION_TYPE ACTUAL.
- Novelty: `novelty.py` on both host URLs and the terms attitude, quaternion, mro_sc_psp, spacecraft, gyro, angular_rate, naif, MRO and "mars reconnaissance". It found no CK or spacecraft-attitude material in recipes, the registry, the ledger or downstream; the nearest matches are DE440s, TUM pose and HAR gyro.
- Scripts: build.sh and verify.sh are local-only (no curl, urllib or subprocess). No credentials appear anywhere.
