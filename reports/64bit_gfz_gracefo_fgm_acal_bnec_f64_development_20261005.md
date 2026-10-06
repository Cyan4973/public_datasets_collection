# GRACE-FO calibrated platform-magnetometer B_NEC float64 development

## Outcome

Accepted `gfz_gracefo_fgm_acal_bnec_f64` after one repair cycle.

This is the first magnetic-field family at 64 bits. It is a low-Earth-orbit vector magnetometer series: the AOCS fluxgate on GRACE-FO 1 and 2, flying a near-polar orbit at about 490 km and sampling at 1 Hz. The only geomagnetic family in the corpus so far is the USGS ground-observatory minute series at 32 bits (`usgs_geomag_observatory_minute_f32`, with a downstream equivalent). That is a different instrument class, platform, cadence and width.

The first judge round found an undocumented problem in GFZ's v0201 files dated 2022-11..2024-11: all seven disturbance-correction variables (`dB_*`) are published as exactly 0.0. The repair kept the selection and the samples unchanged. It disclosed the era truthfully, recorded it per sample in the index, and pinned and re-derived it in build and verify.

## Source and rights

- Source: GFZ ISDC, `https://isdc-data.gfz.de/grace-fo/MAGNETIC_FIELD/0201/GF{1,2}/ACAL_CORR/`
- Product: Michaelis, Stolle, Rother (2021), *GRACE-FO calibrated and characterized magnetometer data*, V. 0201, GFZ Data Services, doi:10.5880/GFZ.2.3.2021.002
- Selection: 64 daily NASA CDF v3 files, 975,321,560 bytes, with per-file size, SHA-256, Last-Modified and ETag pinned in `sources.tsv`
- License: CC BY 4.0, stated in three places:
  - the ISDC `README.txt` in each satellite folder ("License: CC BY 4.0");
  - the DataCite rightsList for the DOI (`cc-by-4.0`, SPDX);
  - the global CDF `License` attribute in every file, checked per file by download, build and verify.

The months 2024-12 and 2025-02 (reprocessed to v0202) and 2026-05 (v0201 withdrawn) are excluded, per the README. download.sh fails if the README names any further reprocessed months.

## Shape and conversion

- **Natural record:** one per-satellite daily ACAL_CORR file.
- **Sample:** that file's complete `B_NEC` zVariable (CDF_DOUBLE, zDims [3], nT, labels Bnorth/Beast/Bcentre), written row-major as `[records, 3]` with N, E, C interleaved, in little-endian binary64. The values are byte-identical to the published big-endian doubles; nothing is rounded or rescaled.
- **Decode:** pure standard library.
  1. Whole-file GZIP from byte 40, after the CCR/CPR records.
  2. Walk the CDR, then the GDR, then the zVDR and ADR chains.
  3. Follow the VXR chain, including next links and nested VXRs.
  4. Gunzip each CVVR block and unpack the values as `>d`.
- **Selection:** slot dates are 2018-06-15 + 45·k days. Even slots take GF1 and odd slots take GF2, falling back to the other satellite on the same date. The two satellites never share a date, because tandem same-day files are near-copies with a 30 s shift.
- **Missing values:** FILLVAL is NaN, and every value must be finite. Timestamps must sit on the exact 1 s day lattice. Up to 10 absent epochs are allowed (upstream omits the record rather than filling it). In practice 4 samples lack exactly one epoch, and the index lists the missing seconds.
- **Disturbance-correction era:**
  - Build classifies each file: either all seven `dB_*` terms are identically 0.0, or none is all-zero. A mixed state is fatal.
  - It records `disturbance_terms_zero` and `disturbance_total_rms_nT` per sample.
  - It pins the 17 zero-era dates. In the other 47 samples the RMS is 12.269–74.042 nT.
  - Verify re-classifies from raw bytes and recomputes the RMS with `math.fsum`.
  - The era is kept inside the family, because its compression statistics match the corrected samples (see Judge checks).

## Accepted output

| item | value |
| --- | --- |
| Primary series | `gracefo_fgm_acal_corr_b_nec_f64` (only series) |
| Samples | 64 (34 GF1, 30 GF2), 2018-06-15..2026-08-02 |
| Primary values | 16,588,788 |
| Primary bytes | 132,710,304 |
| Sample size | 259,200 values (2,073,600 bytes) for 60 samples, 259,197 values for 4 samples |
| Median sample | 259,200 values |
| Value range | -52,823.3..49,185.3 nT |
| \|B\| range | 18,280.6..52,919.7 nT |
| Disturbance era | 17 zero-correction samples, 47 corrected |
| float32-exact values | 0 |
| Rotation identity | B_NEC = conj(q_NEC_FGM)·B_FGM holds to about 6e-11 nT at worst |

Remaining caveats, disclosed in the README:

- B_NEC is a calibrated product from a platform (not science-grade) magnetometer, so residual disturbances remain.
- The 17 zero-era samples carry no disturbance correction.
- B_FLAG semantics are undocumented. Its per-sample nonzero count is recorded, and no records are dropped on it.

## Judge checks

- **Gate:** `python3 tools/autocollect/gate.py staging/gfz_gracefo_fgm_acal_bnec_f64` passes with no warnings.
- **Verify:** I ran `bash staging/gfz_gracefo_fgm_acal_bnec_f64/verify.sh` myself. It returned rc 0 with 64 verified samples and the 17/47 split.
- **Build is local:** build.sh reads only pinned local files. There is no network code on the build path.
- **Independent decode:**
  - I wrote a separate CDF walker in /tmp that does not use `cdf3.py` (sequential record walk, zVDR name match, VXR → CVVR gunzip).
  - It reproduced the sample bytes exactly for GF1 2018-06-15, GF2 2023-12-31 (zero era) and GF2 2026-06-18 (86,399 records).
  - It confirmed that all seven `dB_*` terms are byte-zero in the zero-era file and nonzero in the other two (for example, dB_SA_FGM RMS is 40.1 nT on 2018-06-15).
- **Bytes, all 64 samples:**
  - The ranges are physical for about 490 km altitude.
  - Max 1 s jumps are about 750–810 nT in N and E but only 90–114 nT in C. This is the NEC frame rotating at the pole crossings.
  - The median |Δ²| is 1.2–2.2 nT, the platform noise floor.
  - Low-16-mantissa-bit zero counts sit at chance (1–10 per 259,200 values), so the binary64 values are genuine and not widened.
- **Frame and sign:** against a degree-1 IGRF dipole computed from in-file Latitude/Longitude/Radius (GF1 2024-02-14), the correlations are N 0.887, E 0.622 and C 0.982.
- **Flagged records:** in the two days with the most B_FLAG records (878 and 635), flagged records lie on the same continuum as their neighbours, with somewhat higher |Δ²|. They are not fill values or spikes.
- **Era homogeneity:** median and p90 of |Δ²|, per satellite:

  | satellite | component | corrected (median / p90) | zero era (median / p90) |
  | --- | --- | --- | --- |
  | GF1 | N | 1.89 / 4.96 | 1.72 / 4.56 |
  | GF2 | N | 1.50 / 3.96 | 1.39 / 3.76 |

  The p99 tails are about 20–37% heavier in the zero era on N and E, with C unchanged. That is smaller than the GF1/GF2 difference already inside the family. My conclusion: one compression regime, disclosed rather than re-selected.
- **Rights:** I read the downloaded README ("License: CC BY 4.0") and queried the DataCite API for the DOI (rightsList `cc-by-4.0`). No credentials appear in any script.
- **Novelty:** `novelty.py` on the ISDC URL finds no URL match other than this recipe. No 64-bit magnetic family exists locally or downstream, and no other magnetometer family is among the accepted 64-bit ledger rows.
