# IUE SWP raw camera image uint8 development

## Outcome

Accepted `mast_iue_swp_raw_image_u8`: complete raw 8-bit detector frames from the International Ultraviolet Explorer (IUE) Short-Wavelength Prime (SWP, about 1150-1980 Å) SEC-vidicon camera.

Each sample is one 768 × 768 camera readout in data numbers (DN). It holds:
- the low-dispersion spectrum of the target in the large aperture
- camera and sky background
- reseau marks and cosmic-ray hits
- the dark region outside the circular camera target

All of it precedes any NEWSIPS photometric or geometric correction. This is the corpus's first IUE detector material and its first 8-bit astronomical spectrograph detector frames.

## Source and rights

- **Source:** MAST IUE archive, NEWSIPS raw-image files `https://archive.stsci.edu/missions/iue/data/swp/<block>/swpNNNNN.rilo.gz` (Last-Modified 2013-06-11/12).
  - The MAST file-format page describes RILO as "raw image files (a 768x768 byte primary array image)".
- **Selection catalogue:** the official MAST IUE search interface (CSV output). Of 38,130 SWP low-dispersion images, 16,372 are eligible:
  - large aperture, GSFC station, single exposure, full read, standard acquisition
  - no trail, multiple or segmented flags; exposure > 0
  - object class not 98/99; no calibration words in the target name
- **Strata:** the eligible list is split by image number into 256 strata. The first image per stratum whose FITS header passes the homogeneity keywords is taken. 18 candidates were skipped: 14 for `ABNMINFR`, 4 for `ABNHISTR`.
- **Downloads:** 256 files, 85,299,872 compressed bytes. Each file is pinned by URL, size, gzip CRC32, ISIZE (619,200) and content SHA-256.
- **License:** public domain. The MAST Data Use Policy says "Most data hosted at MAST are in the public domain (see: open data), and therefore do not have restrictions on use." Its only copyrighted collections are the DSS and the GSC; IUE is not mentioned. `download.sh` re-fetches the page and checks both statements.
  - Only frames from the NASA GSFC station are kept.
  - Acknowledge IUE, MAST and STScI.
- **Privacy:** FITS headers contain observer surnames and program IDs. No header text is emitted. Metadata keeps only image number, dates, exposure, object class and astronomical target name.

## Shape and conversion

The natural record is one camera image. Conversion steps:
1. Gunzip each RILO file, requiring CRC32 and ISIZE to match the pins.
2. Parse the 28,800-byte FITS header to `END`.
3. Require all of the following:
   - `BITPIX=8`, `NAXIS1=NAXIS2=768`, `BUNIT=DN`, no `BZERO`/`BSCALE`/`BLANK`
   - `CAMERA=SWP`, `DISPERSN=DISPTYPE=LOW`, `APERTURE=LARGE`, `READMODE=FULL`
   - `READGAIN=LOW`, `EXPOGAIN=MAXIMUM`, `UVC-VOLT=-5.0`, `STATION=GSFC`
   - all `ABN*` flags `NO`, `LEXPTRMD=NO-TRAIL`, `LEXPMULT=LEXPSEGM=NO`
4. Emit the 589,824-byte primary data unit unchanged. The 576 FITS padding bytes must be zero.

Nothing is masked, cropped, scaled or tiled. Edge rows near zero and saturated 255 DN pixels are genuine and kept.

The candidate card proposed the legacy IUESIPS VICAR `.raw.gz` files with a fixed 7,560-byte label. The builder found that label length varies (21 or 22 records of 360 bytes), so it switched to RILO. The judge confirmed that the RILO data unit for swp28705 is byte-identical to the VICAR raw pixels.

## Accepted output

| Item | Value |
|---|---|
| Series | `iue_swp_lowdisp_raw_dn_u8` (primary, native_numeric, uint8) |
| Samples | 256 |
| Values per sample | 589,824 (768 × 768) |
| Primary values / bytes | 150,994,944 |
| Download bytes | 85,299,872 |
| Image range | SWP 506-55694 |
| Observation years | 1978-1995 (18 years, 6-17 frames per year) |
| Object classes / targets | 59 / 218 |
| Thousand-image directories | 55 |
| Exposure | 1.508-25,199.689 s (median about 1,500 s) |
| Distinct DN per frame | 223-256; aggregate uses all 256 levels |
| Frame mean DN | 11.33-108.82 |
| Central 256 × 256 mean | 16.26-164.99 DN |
| Max 64 × 64 corner mean | 1.19 DN |
| Zero / saturated pixels (aggregate) | 17.73% / 0.032% |
| zlib-6 ratio per frame | 0.419-0.709 (median 0.48) |
| Aggregate sample SHA-256 | `f2d495893b4f56764cb974b25cd72981e09a434911d1bcb7c591fc3cf71bfa12` |

## Judge checks

- **Gate:** `gate.py` PASS with no warnings.
- **verify.sh** (run by the judge): `verify ok samples=256 bytes=150994944 dn_levels=256`.
- **Tamper test:** in a scratch `DATA_DIR`, one flipped bit in `swp28705.u8` made verify fail with "emitted sample differs".
- **Script timing:** `download.sh` and its parsers were last modified before the driver's download. The SHA-256 column added afterward matches `download_plan.tsv` for all 256 files.
- **Local-only build:** `build.sh` and `verify.sh` read only local files; no curl or network imports. No credential patterns in any script (quoted-glob grep).
- **Byte inspection (stdlib):**
  - per-frame statistics for all 256 samples
  - coarse block maps showing the circular target, dark corners and the diagonal spectral trace
  - zero rows only at the top edge; no mid-frame dropouts
  - no target-region row segment shared across frames
  - closest pair about 0.9 DN mean difference, from different years: shared camera pattern plus noise, not duplicates
- **Native check:** the judge fetched `swp28705.raw.gz` (VICAR, 597,384 bytes, 7,560-byte label). Its pixels equal the emitted sample byte for byte.
- **Rights:** the judge opened the MAST data-use page. It confirms the public-domain sentence, the DSS/GSC-only copyrighted list, and no IUE or foreign-mission carve-out. I reviewed all 218 target names: all are astronomical designations.
- **Novelty:** `novelty.py` (IUE URL, terms iue/international ultraviolet/vidicon/rilo/ultraviolet) found no URL, registry or downstream matches. The only other IUE material is one extracted-spectrum FITS sample at 32/64 bits in `nasa_fits_sample_image_planes`. The 8-bit list has no astronomical detector frames. Label: `new_source`.
