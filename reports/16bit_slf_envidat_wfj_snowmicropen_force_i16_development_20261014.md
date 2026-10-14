# SLF WFJ_DailySMP SnowMicroPen S36M penetration-force int16 development

## Outcome

Accepted `slf_envidat_wfj_snowmicropen_force_i16`. It collects native signed-int16 piezo force ADC counts from the SLF SnowMicroPen (SMP), a motorised micro-penetrometer. The SMP drives a 5 mm tip through the snowpack at 20 mm/s and samples force every 0.00413223 mm.

- Profiles come from the daily WFJ_DailySMP protocol at the Weissfluhjoch (Davos) study plot.
- Device: S36M (SMP serial 36, v4 electronics, firmware 406/408).
- Each sample is one complete vertical penetration profile (one `.PNT` file).

This is new material for the corpus. No penetrometry or mechanical-resistance profile exists at any width, locally or downstream:
- `zenodo_gpr_rd3_i16` holds radar traces, which are a different physics.
- `figshare_fukuchi_forceplate_c3d_f32` holds force time series from gait, not depth profiles.

## Source and rights

- Source: EnviDat package `wfj_dailysmp`, "WFJ_DailySMP - High-Resolution Snow Stratigraphy at Weissfluhjoch -- Davos 2015-ongoing", DOI 10.16904/envidat.641.
- Bucket: public SWITCH S3 bucket `zhc-c.s3.cloud.switch.ch/envidat-doi/10.16904_envidat.641/data/`, read anonymously.
- Archive: `raw_data.zip`, 3,134,603,173 bytes, ETag `dee701a233d33d5bb2eb55f713240b99-598`, 16,535 entries. It is never downloaded whole:
  - Only the central directory (1,638,152 B including the EOCD) is range-fetched.
  - Then the 291 pinned members are fetched: 149,338,897 compressed bytes, 239,853,056 inflated.
  - Each member is pinned by local-header offset, compressed and uncompressed size, and CRC32 in `members.tsv`.
- Selection metadata: `raw_data.csv` (md5 `40f11a5f364afd964e7e6e3ef65df1e5`; columns Date, File, Path, BestOfDay, Quality) and `Readme.pdf` (md5 `cf7599b841ab2f5c0c5bad810b1eb6e4`). The Readme documents the Quality flag (1 = good; recommended).
- License: EnviDat `package_show` reports `license_id: cc-by-sa`, URL https://creativecommons.org/licenses/by-sa/4.0/. `download.sh` re-checks this field and the DOI on every run.
- The same `data/` folder carries an MIT `LICENSE` (md5 `e240a6501986482bf61ce32ab34d95fd`, "Copyright (c) 2025 WSL Institute for Snow and Avalanche Research SLF"). Both licenses are permissive and both are cited.
- No personal data: physical snow measurements at a research plot.

## Shape and conversion

Selection:
1. `raw_data.csv` has 478 rows with File starting `S36M` and BestOfDay=1.
2. Keeping Quality=1 leaves 438.
3. Keeping PNT-header sensor and amplifier range 5000 pC leaves **291**.

The 147 Quality=1 profiles recorded at range 10000 pC (2019-03-27..2020-12-16) use a conversion factor of 0.0026 N/count, a 2x coarser scale. They are excluded as a different regime and pinned in `excluded_gain10000.tsv`.

Within the kept set, five force sensors give three header conversion factors (±0.9%):

| Factor (N/count) | Profiles |
|---|---|
| 0.0013042 | 228 |
| 0.0012932 | 61 |
| 0.0013155 | 2 |

Factors are recorded per sample in the index and not applied.

Decode follows snowmicropyn's `Pnt.load`:
- 512-byte big-endian header.
- `samples.force.count` is `>l` at offset 358.
- That many `>h` force counts start at byte 512.
- Bytes after the counted samples are padding (0x7fff, 0xffff or a held last value) and are ignored.
- Output is little-endian int16 in source order, one `.bin` per profile.

The card's SMP5 assumption (1024-byte header, count at offset 2) does not apply to S36M. On these files the offset-2 field always exceeds the file's capacity.

`build.sh` asserts per profile:
- firmware 406/408;
- SMP serial 36;
- header filename equals the member stem;
- resolution 0.00413223 mm, speed 20 mm/s, tip 5000 µm;
- conversion factor in [0.00129, 0.00132] and equal to the pinned value;
- count equal to the pinned count.

Native content is kept whole: the air segment above the surface, the full snowpack, and the ~40 N overload plateau at the bottom of some profiles (header overload 40 N). The first word at byte 512 is an outlier in 185 profiles. It is kept, as the reference reader returns it as sample 0.

## Accepted output

- Source members: 291 of 16,535 zip entries (149,338,897 B transferred)
- Primary samples: 291 (one per date, 2015-11-30..2020-12-21)
- Winters: 2015/16 101, 2016/17 27, 2017/18 69, 2018/19 85, 2020/21 9. 2019/20 is absent: it was recorded entirely at range 10000.
- Primary values: 119,708,056
- Primary bytes: 239,416,112
- Minimum sample: 80,449 values
- Median sample: 478,499 values
- Maximum sample: 508,200 values (= 2100 mm stroke / 0.00413223 mm)
- Value range: -1,303..32,767
- Global percentiles (1/50 subsample): p1 10, p50 657, p90 4,007, p99 9,215
- Distinct values per profile: about 3,800–13,000

## Judge checks

- **Gate:** `gate.py` PASS, no warnings (widths=[16]).
- **Verify:** `verify.sh`, rerun by the judge, passes in 12 s. It checks:
  - kept plus excluded equals exactly the 438 Quality=1 rows;
  - a struct re-decode that is byte-equal to every sample;
  - sha256, min/max/distinct and the >50% single-value check;
  - manifest totals.
- **Upstream integrity:** the judge recomputed CRC32 and size of all 291 local members against `members.tsv`: 0 mismatches.
- **Independent decode:** the judge fetched snowmicropyn's `pnt.py` and confirmed the header table: count at 358 (`>l`), conv at 10, data from 512. The judge's own struct decode reproduces S36M0057, S36M5860 and S36M9038 byte for byte.
- **Header fields** (all 291 profiles): offset_force 0; overload 40 N (289) or 41 N (2); sensitivity 116–118 pC/N; temperature count 0. Padding after the count is 216–768 slots.
- **Distributions:**
  - Air baseline is 9–30 counts. Four deep-snow 2018 full-stroke profiles start at 111–429 but still reach a floor of 28–32.
  - Order-0 entropy is 8.22–13.47 bits per profile (median 11.05); delta entropy is 3.54–8.01.
  - Mode share is 0.17–10.0% (median 1.7%).
  - The trailing overload run is at most 0.73% of a profile.
  - Negative counts are at most 0.18% of a profile.
- **Duplicates:** sha256 and dates are unique. Adjacent-day profile pairs share no 64-value windows.
- **Novelty:**
  - `novelty.py --url` matches only the candidate itself.
  - Terms (SnowMicroPen, penetrometer, cone penetration, envidat, weissfluhjoch, snow profile, stratigraphy) return only unrelated families.
  - `--type`, `--instrument` and `--archive` each return 0.
  - zlsim breadth OK: nearest is downstream `mola_megdr_topography_i16` at 0.088 (loss 0.089), mode share 5.0%.
- **Rights:** the judge read `package_show.json` (cc-by-sa, DOI matches, published, not private) and the MIT `LICENSE` text directly. The scripts contain no credentials. CC-BY-SA data has precedent in accepted manifests.

### Documentation notes for a follow-up edit

These do not affect the bytes, so they were not worth a repair cycle:

- The manifest `description` says "winters 2015/16-2020/21". No 2019/20 profiles are kept (that winter is all range 10000), and 2020/21 contributes only 9 December profiles. A precise date list would read better.
