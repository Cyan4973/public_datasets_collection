# STEREO-A IMPACT/MAG Level-1 RTN interplanetary magnetic field float32 development

## Outcome

Accepted `stereo_a_impact_mag_rtn_bfield_f32` after one repair cycle.

The recipe collects in-situ heliospheric (solar-wind) magnetic field vectors from the IMPACT/MAG fluxgate magnetometer on NASA's STEREO-Ahead spacecraft. Typical values are a few nT, with turbulent sign changes in every component.

This is new content in a known modality:
- The local corpus already has ground-observatory geomagnetic field series at 32 bits (`usgs_geomag_observatory_minute_f32`).
- It also has an LEO platform magnetometer at 64 bits (`gfz_gracefo_fgm_acal_bnec_f64`).
- Neither has 8 Hz interplanetary-field turbulence.

The first review requested two fixes, and both are in place:
1. **UTC-day trim.** Every sample is now trimmed to its UTC day. The CDF 3.7 files carried 3–41 next-day records each. In `STA_L1_MAG_RTN_20231231_V06` those records were a non-physical offset step at the 2023→2024 rollover (|B| 8.34 → 46.63 nT in 125 ms).
2. **Metadata anomaly documented.** The CDF 3.7 files carry a BFIELD CATDESC copied from the SC-frame product template. The data are nevertheless the RTN rotation, and this is now documented.

## Source and rights

- **Source:** STEREO Science Center (NASA GSFC), `https://stereo-ssc.nascom.nasa.gov/data/ins_data/impact/level1/ahead/mag/RTN/`.
- **Product:** daily `STA_L1_MAG_RTN_YYYYMMDD_V06.cdf`.
- **Pinned files:** 50 files, 999,050,619 bytes. `sources.tsv` records the exact URL, size, Last-Modified and SHA-256 of each file.
- **Selection:** `discover.sh` lists all V06 normal-mode days from 2007-01-01 to 2023-12-31 whose listing size is 18M or 19M. That gives 4,914 eligible near-complete 8 Hz days, and 50 are taken at even rank spacing.
- **License:** CC0 1.0 under the NASA Science Data license. That license states: "Unless the data file is marked with a restrictive notice or license, data that is provided from a NASA-led mission including observations, engineering, calibration, and auxiliary data are licensed as Creative Commons Zero."
  - STEREO is a NASA Solar Terrestrial Probes mission.
  - The CDFs carry no Rules_of_use or license attribute, and the build fails if one appears.

## Shape and conversion

**Natural record.** One UTC-day Level-1 CDF.

**Decoding.**
- The `BFIELD` zVariable is CDF_FLOAT `[N, 4]` = BR, BT, BN, BTotal, in nT.
- It is decoded with a pure-stdlib reader that handles both internal layouts the archive uses:
  - CDF 2.7 (41 files, through 2021-05);
  - CDF 3.7 (9 files, from 2021-09).
- The reader walks CDR → GDR → zVDR chain → full VXR list including child VXRs → VVRs.
- It requires record coverage 0..MaxRec.

**Output.** Each component becomes its own little-endian float32 series via a pure byte-swap with no arithmetic. BTotal is the source's own published 4th component.

**Missing-value policy (shared by build and verify):**
1. Records whose Epoch lies outside [day_lo, day_hi) of the pinned date are dropped from all four series. Here day_lo = (ordinal − 1 + 366) · 86,400,000 ms in CDF_EPOCH. More than 2,400 such records in one file is fatal.
2. Records with any component equal to -1e31 or non-finite, or with a fill Epoch, are dropped from all four series.
3. Non-fill values outside VALIDMIN/VALIDMAX, or more than 5% fill in a day, are fatal.

**Consistency checks.** The build also requires:
- BTotal ≈ |(BR,BT,BN)| for at least 99.9% of kept records;
- a median Epoch step of 124–126 ms.

## Accepted output

| Item | Value |
|---|---|
| Source files decoded | 50 (41 CDF 2.7, 9 CDF 3.7) |
| Source records | 34,386,826 |
| Records dropped outside the UTC day | 208 (0 in the 2.7 files; 31/41/4/28/3/13/36/37/15 in the 3.7 files) |
| Fill records dropped | 40 (3.7 files only; isolated whole-record fills) |
| Kept records | 34,386,578 per series |
| Series | `sta_mag_rtn_br_f32`, `sta_mag_rtn_bt_f32`, `sta_mag_rtn_bn_f32`, `sta_mag_rtn_btotal_f32` |
| Samples | 200 (50 per series) |
| Primary values | 137,546,312 |
| Primary bytes | 550,185,248 (137,546,312 per series) |
| Sample size | min 627,310 values, median 691,170.5 values, max 691,201 values |
| Date span | 2007-01-01 to 2023-12-31 |
| Aggregate SHA-256 | `4891a7ce4a66adadb0ca2abd4cfc32e7012c050120e8265488c5a360a9883908` |

zlsim breadth (measured by the driver) is OK. Nearest distances are:

| Series | Nearest distance | Nearest family |
|---|---|---|
| BR | 0.078 | h1_etad0_d |
| BT | 0.072 | ERA5 geopotential |
| BN | 0.082 | AhmedML mean pressure |
| BTotal | 0.060 | h1_dmd0_d |

## Judge checks

- **Mechanics.** I ran `gate.py` myself: PASS, no warnings, the same totals as above.
- **Reproducibility.** I ran `verify.sh` myself: exit 0, `verify ok: files=50 samples=200 bytes=550185248`.
  - Verify independently re-decodes every file per record, re-applies the trim and fill policy, and byte-compares all 200 samples.
  - `build.sh` uses only the local `.data/downloads/` files.
- **Independent bytes check.** I wrote my own minimal CDF walker, separate from the recipe's `cdfread.py`. Its day bound is anchored on CDF_EPOCH(2000-01-01) = 63113904000000 ms.
  - It reproduced the trimmed, fill-dropped samples byte for byte for all 4 components of 20231231 (v3.7), 20210919 (v3.7) and 20130527 (v2.7 with a gap).
  - The 20231231 spill is the contiguous final records 691161–691175, beginning 40 ms after midnight with the offset step. It is excluded.
- **Physical plausibility, over all 200 samples:**
  - Components lie within ±15 nT. |B| spans 0.022–16.9 nT, with daily means of 2.5–12 nT.
  - Distinct fraction is 0.70–0.99, mode share ≤7e-5, median |step| 0.014–0.047 nT.
  - 20231231's largest |B| step is now 0.42 nT.
  - The largest step in the family is +5.69 nT in |B| on 2012-06-25, from 5.69±0.15 to 12.77±0.37 nT. It has the signature of an interplanetary shock, not an artifact.
- **Rights.** I opened the NASA Science Data license page and confirmed the CC0 default for NASA-led missions. The recipe scripts contain no credentials.
- **Novelty.** `novelty.py` URL, term, type, instrument and archive checks show no matching downstream or accepted IMF family. The magnetometer modality exists at 32 bits only as ground-observatory data, hence `new_content_same_modality`.
- **Remaining limitations, accepted:**
  - BTotal is largely redundant with the three components, but it is a native published field and zlsim measures it as distinct.
  - Four days keep 91–96% of a full day because of telemetry gaps, which are not interpolated.
  - The output is 550 MB, above the roughly 100 MB that downstream sub-samples per family, but within the 1 GB cap.
