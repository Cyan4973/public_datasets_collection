# STEREO-A IMPACT/MAG Level-1 interplanetary magnetic field (RTN, 8 Hz), float32

This recipe collects in-situ heliospheric (solar-wind) magnetic field vectors
measured by the IMPACT/MAG fluxgate magnetometer on NASA's STEREO-Ahead
spacecraft. Values are a few nT, with turbulent sign changes in each component.
Each source file is one UTC day (trimmed by Epoch, see below) of the Level-1 **normal-mode** product
`STA_L1_MAG_RTN_YYYYMMDD_V06.cdf`, which holds 8 vectors/s in RTN coordinates.
The recipe emits the native `BFIELD` CDF_FLOAT `[N, 4]` variable as four
separate little-endian float32 series, one sample per component per day:

| series | BFIELD component | label |
|---|---|---|
| `sta_mag_rtn_br_f32` | 0 | BR |
| `sta_mag_rtn_bt_f32` | 1 | BT |
| `sta_mag_rtn_bn_f32` | 2 | BN |
| `sta_mag_rtn_btotal_f32` | 3 | BTotal (published magnitude) |

The four components are emitted as separate series and are never interleaved.

## Homogeneity choices

- STEREO-A only (Behind ended in 2014), RTN frame only (the SC-frame files
  are excluded).
- Normal-mode `MAG` only. The burst `MAGB` files run at a different cadence
  and cover partial days, so they are excluded.
- Only version V06 (`Data_version` 6). V03, V04, V05 and V07 coexist in some
  months and are excluded.
- Only near-complete 8 Hz days: files whose listing size is 18M or 19M. Partial
  days near the 2014-2015 solar conjunction ran at 4 Hz and are 1-3 MB.
  Build fails unless the median Epoch step is 124-126 ms.

## Selection

`discover.sh` documents the selection. It crawls all month listings, dedupes
hrefs and days listed under two month directories, keeps the 4,914 eligible
V06 days dated 2007-01-01..2023-12-31, and takes 50 at even rank spacing.
There are none in 2015 and a 2014-07..2016-02 gap around the conjunction. The
result is pinned in `sources.tsv`: 50 files, 999,050,619 bytes, exact sizes
and Last-Modified.

## Decode

`scripts/cdfread.py` is a pure-stdlib CDF reader for both internal layouts the
archive uses: CDF 2.7 (32-bit offsets; the 41 pinned files through 2021-05)
and CDF 3.7 (64-bit offsets; the 9 pinned files from 2021-09 on, which also
omit the `Logical_file_id` attribute). Both carry the same V06 product.

The CDF 3.7 files also have wrong metadata copied from the SC product:
BFIELD CATDESC "Magnetic field vector in Spacecraft coordinates ...",
FIELDNAM "B Field in Spacecraft Coordinates" and Time_resolution
"00:00:00.032". The first 64 KiB of `STA_L1_MAG_RTN_20230922_V06.cdf` is
byte-identical to `STA_L1_MAG_SC_20230922_V06.cdf`. The BFIELD data are still
the RTN rotation:
- The acceptance judge compared record 0 of 20230922 in both products: RTN
  (-1.8627, -1.6985, -3.2848, 4.1405) against SC
  (1.8627, -3.3119, -1.6449, 4.1360), i.e. BR = -X_sc.
- The Parker-spiral sign fraction (BR·BT < 0) averages 0.689 on the 9 CDF 3.7
  days and 0.688 on the 41 CDF 2.7 days.

`ingest_stats.json` records each file's CDF version and BFIELD CATDESC.

Reader path:
CDR → GDR → zVDR chain → ADR/AEDR attributes → the full VXR linked list,
recursing into child VXRs → VVR records. It requires coverage of records
0..MaxRec and clips preallocated VVR tails. `build.sh` first runs a synthetic
self-test, in both the v2 and v3 layouts: a hand-built CDF with 6 VVR segments across chained and child VXRs,
fill records, and corruption cases.

## UTC-day trim

Each sample is exactly one UTC day. Records whose Epoch falls outside
[day_lo, day_hi) of the `sources.tsv` date are dropped from all four series
before the fill logic. CDF_EPOCH is in ms since 0000-01-01, so
`day_lo = (date.toordinal() - 1 + 366) * 86,400,000`. A file that drops more
than 2,400 records this way (5 minutes) is fatal. Build and verify both check
that the first and last kept Epoch lie inside the day.

The CDF 2.7 files drop nothing. Each of the 9 CDF 3.7 files carries 3–41
leading records of the next day: 31, 41, 4, 28, 3, 13, 36, 37 and 15, for 208
in total. In `STA_L1_MAG_RTN_20231231_V06` those 15 records
(2024-01-01T00:00:00.040–00:00:01.790) are a non-physical step at the year
rollover: |B| jumps from 8.34 to 46.63 nT in one 125 ms step, with BR/BT/BN
offset by about +22/+31/+13 nT, apparently from uncorrected sensor offsets.
After the trim, the largest |B| step in that sample is 0.42 nT.

## Missing values

After the UTC-day trim, a record is dropped from all four series when any component equals FILLVAL
(-1e31, which the source FILTER_VALUE spike filter also uses), is non-finite,
or has a fill Epoch. More than 5% fill in a day, or non-fill values outside
VALIDMIN/VALIDMAX, are fatal. Telemetry gaps are not interpolated.

## License

NASA science data license: data from NASA-led missions are CC0 unless the file
is marked with a restrictive notice (https://science.data.nasa.gov/about/license).
The CDFs carry no `Rules_of_use` or license attribute, and build fails if one
appears.

## Run

```bash
bash staging/stereo_a_impact_mag_rtn_bfield_f32/download.sh
bash staging/stereo_a_impact_mag_rtn_bfield_f32/build.sh
bash staging/stereo_a_impact_mag_rtn_bfield_f32/verify.sh
```
