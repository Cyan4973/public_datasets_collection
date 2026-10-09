# GOES-16 EXIS/XRS 1-second solar soft X-ray flux float32 development

## Outcome

`noaa_goes16_xrs_1s_flux_f32` is accepted. It collects the whole-Sun soft X-ray flux at 1-second cadence from the GOES-16 EXIS X-Ray Sensor. The source is the NOAA NCEI science-quality Level-2 product `xrsf-l2-flx1s_science`, version v2-2-1. The two primary channels go into separate series:

- `goes16_xrsa_flux_1s_f32`: XRS-A, 0.05-0.4 nm
- `goes16_xrsb_flux_1s_f32`: XRS-B, 0.1-0.8 nm, the band that defines the flare classes

No high-cadence solar irradiance time series existed at any width, locally or downstream. The nearest relatives are:

- SILSO sunspot indices
- the DONKI flare event catalog
- TESS light curves
- USGS geomagnetic minute series

The byte-level breadth verdict is STRONG. The nearest family is 0.085 away for XRS-A and 0.121 away for XRS-B.

## Source and rights

- Archive: `https://data.ngdc.noaa.gov/platforms/solar-space-observing-satellites/goes/goes16/l2/data/xrsf-l2-flx1s_science/YYYY/MM/sci_xrsf-l2-flx1s_g16_dYYYYMMDD_v2-2-1.nc`
  - one NetCDF4/HDF5 file per UTC day
  - 2,981 days from 2017-02-07 to 2025-04-06, no gaps
  - all reprocessed 2025-12-05
- Download: 196 files, 676,343,852 bytes. The exact size and SHA-256 of every file is pinned in `files.tsv`.
- License: every file carries the global attribute `license = "These data may be redistributed and used without restriction. "` and `institution = "DOC/NOAA/NESDIS"`.
  - The NCEI ISO 19115 record `gov.noaa.ncei.swx:exis-l2-goesr` lists only a citation request and the standard NOAA no-warranty disclaimer.
  - The data is a U.S. Government work.
- Citation: Machol, Codrescu and Viereck, *GOES-R Series EXIS Level 2 Products*, NOAA NCEI 2018, doi:10.25921/94P8-YE57.

## Shape and conversion

- Natural record: one daily file variable, 86,400 one-second records.
- Selection: the 1st and 15th of every month from 2017-02-15 to 2025-04-01, a fixed calendar rule giving 196 of 2,981 days. It covers both the 2018-2020 solar minimum and the cycle-25 maximum.
  - The full archive would be about 2 GB of output, which exceeds the 1 GB cap.
- Decode: the pure-stdlib `h5lite.py` reader, byte-identical to the accepted sea-ice recipe's copy. It verifies the lookup3 checksum of every metadata block it reads.
  - The datatype must be exactly little-endian IEEE float32 and the shape (86400,).
  - The filter pipeline must be exactly [shuffle(4), deflate], with a single chunk indexed by a version-1 B-tree.
  - The chunk must inflate to exactly 345,600 bytes; the shuffle is then inverted and the stored words are written unchanged.
- Per-file checks:
  - global id equals the filename;
  - `time_coverage_start` equals the filename date;
  - platform, title, license and institution attributes;
  - units `W/m2` and `_FillValue` -9999;
  - the float64 time axis is strictly increasing and lies within the UTC day.
- Missing values: `_FillValue` -9999 is kept in place as the word `0xC61C3C00`. A day is dropped for both channels if either channel is more than 50% fill/NaN or has fewer than 100 distinct valid values.
- Flags: records flagged for eclipse or particle spikes keep their published values, and the flags are not emitted.
- `au_factor` is not applied, so fluxes are as measured at the spacecraft.

## Accepted output

- Inventory days: 196. Days dropped: 2, 2017-05-01 and 2017-12-01, both 100% fill in both channels.
- Primary samples: 388 (194 per series), each 86,400 float32 values.
- Primary values: 33,523,200. Primary bytes: 134,092,800 (67,046,400 per series).
- Value range:
  - XRS-A: -8.82e-8 to 2.622e-4 W/m2
  - XRS-B: -6.62e-8 to 7.089e-4 W/m2
- Fill: 17,353 values per series in total (about 0.1%). The worst day is 2024-09-15 at 7.38%. There is no NaN.
- Distinct valid values per day:
  - XRS-A: min 1,038, median 5,376, max 35,224
  - XRS-B: min 1,702, median 20,344, max 69,380
- Aggregate SHA-256 of the samples in index order: `57cb27c1bb99cd2d53d0f29b15d47f48ef3aa966062c7eccba20177537206c4e`

## Judge checks

- **Gate:** `gate.py` passes with no warnings.
- **Verify:** I reran `verify.sh` and got verify=ok, days=196, excluded=2, rows=388, with all 388 samples byte-compared against the independent decode.
- **Reproducibility:**
  - build reads only local files; network access appears only in `plan` and download.sh;
  - `h5lite.py` diffs clean against `datasets/noaa_cdr_seaice_conc_nh_daily_u8`;
  - three spot-checked downloads match the pinned size and SHA-256;
  - 196/196 files are present.
- **Bytes:** I sampled 5 days per series across 2017-2025 with `struct`.
  - Medians track the solar cycle: about 7e-9 at the 2018-2019 minimum, up to 8e-6 for XRS-B in 2024.
  - Flare peaks match published events to the second: 7.089e-4 at 22:20:14 UT on 2024-10-01 (X7.1) and 3.455e-4 at 08:37:48 UT on 2024-05-15 (X3.4). This confirms both the decode and the time alignment.
  - Negative noise-floor values and quiet-day repeats (ADC quantization) are real instrument behaviour.
  - All 388 sample hashes are unique.
- **Rights:** I fetched the ISO record myself and found only the citation request and disclaimer. A raw-byte search found the license and institution attributes in all 196 files. No credentials are used and there is no personal data.
- **Novelty:**
  - `novelty.py --url` matches only this staging recipe.
  - `--terms` matches only the DONKI flare catalog (event records) and unrelated ABI cloud-mask entries.
  - `--type/--instrument/--archive` return 0/0/0.
  - The downstream 32-bit families have no solar irradiance series.
  - No accepted manifest uses the `data.ngdc.noaa.gov` host. RSTN uses `www.ngdc.noaa.gov`, so the third-acceptance-per-host sign-off does not apply.
- **Notes:** a few manifest and README phrases describe "probed days" (XRS-A minimum about -2e-8, fill 0-481). The realized extremes are a minimum of -8.8e-8 and a fill maximum of 6,379 on 2024-09-15. Those realized figures are recorded in `deterministic_notes` and `ingest_stats.json`, so this is a documentation nit, not a scope misstatement. The builder's note that zlsim was unmeasured is superseded by the driver's STRONG measurement.
