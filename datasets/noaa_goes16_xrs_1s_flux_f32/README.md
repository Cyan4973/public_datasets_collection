# noaa_goes16_xrs_1s_flux_f32

GOES-16 EXIS X-Ray Sensor (XRS) science-quality Level-2 1-second solar soft
X-ray flux (NOAA NCEI product `xrsf-l2-flx1s_science`, version v2-2-1), native
float32.

## What is collected

| series | source variable | band | unit | sample |
|---|---|---|---|---|
| `goes16_xrsa_flux_1s_f32` | `xrsa_flux` | XRS-A 0.05-0.4 nm | W/m^2 | one UTC day, 86,400 float32 |
| `goes16_xrsb_flux_1s_f32` | `xrsb_flux` | XRS-B 0.1-0.8 nm | W/m^2 | one UTC day, 86,400 float32 |

- Scope: 196 days, the 1st and 15th of each month from 2017-02-15 to
  2025-04-01. The calendar rule was fixed before looking at the data. It
  covers the solar minimum of 2018-2020 and the cycle-25 maximum of 2023-2025.
  The archive holds 2,981 days with no gaps, so this selection is about 6.6%.
- Output: 388 samples, 134,092,800 bytes. 194 days are kept; 2017-05-01 and
  2017-12-01 are 100% fill in both channels and are dropped.
- Download: 676,343,852 bytes. Every file's size is pinned in `files.tsv`.
- XRS-A and XRS-B are separate series. They are different bands, and XRS-B
  typically runs about 10x higher.
- Values span roughly -2e-8 to 4e-4 W/m^2 in the probed days: quiet Sun
  through an X-class flare on 2024-05-10, which is not in the selection.
- Only the primary-channel flux variables are emitted. Excluded:
  - per-diode fluxes (`xrsa1/a2/b1/b2_flux`)
  - flags, primary-channel indicators, corrected currents
  - `au_factor`, roll and yaw, and `time`

## Source and license

- Archive:
  `https://data.ngdc.noaa.gov/platforms/solar-space-observing-satellites/goes/goes16/l2/data/xrsf-l2-flx1s_science/YYYY/MM/`
- Each file carries the global attribute
  `license = "These data may be redistributed and used without restriction. "`
  and `institution = "DOC/NOAA/NESDIS"`. Download, build and verify check
  both in every file.
- The NCEI ISO record `gov.noaa.ncei.swx:exis-l2-goesr` lists only a citation
  request and a liability disclaimer.
- U.S. Government work. Cite: Machol, Codrescu and Viereck, *GOES-R Series
  EXIS Level 2 Products*, NOAA NCEI 2018, https://doi.org/10.25921/94P8-YE57.

## Decode

The files are NetCDF4 (HDF5 1.14.3, superblock v2). Decoding uses
`scripts/h5lite.py`, copied unchanged from
`datasets/noaa_cdr_seaice_conc_nh_daily_u8`. It is pure stdlib and verifies
the lookup3 checksum of every metadata block it reads.

For each variable the decoder:

1. resolves the variable by link name through dense link storage;
2. requires:
   - an exact little-endian IEEE float32 datatype message;
   - dataspace `(86400,)`;
   - filters exactly `[shuffle(4), deflate]`;
   - a single chunk with filter mask 0;
3. inflates the chunk to exactly 345,600 bytes and inverts the byte shuffle;
4. writes the stored 32-bit words unchanged.

Per-file checks:

- global `id` equals the filename, and `time_coverage_start` equals the
  filename date;
- platform, title, license and attribute checks;
- the float64 `time` axis is strictly increasing and lies within the UTC day.

Build resolves links through the name index. Verify resolves them
independently through the creation-order index, un-shuffles with separate
code, classifies values by bit pattern, and byte-compares every sample.

`scripts/selftest_xrs.py` builds synthetic HDF5 files with the same
structures. It checks both decoders and the rejection cases: wrong
date/license/datatype/shuffle size, a truncated chunk, a missing variable, a
bad time axis, and corrupted checksummed blocks. It runs before build and
verify.

## Missing values

- `_FillValue` -9999.0 is preserved in place as the stored word `0xC61C3C00`.
  NaN would be preserved bit-exactly.
- The index records `fill_count` and `nan_count` per sample.
- Probed days hold 0-481 fill values and no NaN.
- Records flagged as eclipse, particle spike or calibration keep their
  published flux values. The flags are not emitted.
- A day is dropped for both channels if either channel is more than 50%
  fill/NaN or has fewer than 100 distinct valid values. Dropped days are
  listed in `filtered/<id>/ingest_stats.json`, and verify re-derives the same
  set.
- Infinite values are fatal.

## Files

- `files.tsv`: pinned date, filename, byte size, and SHA-256 for all 196
  files (`-` would mean unpinned; none remain).
  `check-downloads` writes the observed SHA-256 of every file to
  `downloads/<id>/observed_sha256.tsv`.
- `download.sh`:
  1. one-byte liveness probe;
  2. resumable curl passes into `.part` files;
  3. size and SHA check, then promote;
  4. full semantic decode of every file.
- `build.sh`, `verify.sh`, `scripts/xrs_flux.py`, `scripts/verify_xrs.py`,
  `scripts/selftest_xrs.py`.
