# DESI DR1 coadded flux (B/R/Z arms) float32 development

## Outcome

Accepted `desi_dr1_coadd_dark_flux_f32`. Each primary sample is one whole `<ARM>_FLUX` image HDU from a DESI Data Release 1 (spectroscopic production `iron`) main-survey, dark-program healpix coadd file. Each arm is its own float32 series:

- `desi_coadd_b_flux_f32`: 2751 wavelength pixels, 3600–5800 Å
- `desi_coadd_r_flux_f32`: 2326 pixels, 5760–7620 Å
- `desi_coadd_z_flux_f32`: 2881 pixels, 7520–9824 Å

These are the corpus's first astronomical, extracted, optical 1-D spectra. Until now the 32-bit `spectrum_1d` family held only laboratory spectra: soil MIR, marine DOM MS1 and powder XRD. The novelty is a new source within an existing modality. zlsim measured breadth as OK; the nearest family on every series is `physionet_eit_thorax_images_f32`, at distance 0.0891 (B), 0.0662 (R) and 0.0821 (Z).

## Source and rights

- Source: `https://data.desi.lbl.gov/public/dr1/spectro/redux/iron/healpix/main/dark/<group>/<healpix>/coadd-main-dark-<healpix>.fits`
  - 223 healpix groups at discovery.
  - Files last modified 2023-01-30 and 2023-01-31.
- Pinning: each of the 36 files is pinned by Content-Length, Last-Modified and the primary-header SHA-256. Each of the 108 FLUX HDUs is pinned by:
  - header offset and length
  - header SHA-256
  - NAXIS1 and NAXIS2
  - data-unit length
  - FITS `DATASUM`
- License: CC BY 4.0.
  - DESI data license page: "The Dark Energy Spectroscopic Instrument (DESI) data are licensed under the Creative Commons Attribution 4.0 International License ... free to share, copy, redistribute, adapt, transform, and build upon the DESI data available through this website for any purpose, including commercially".
  - DR1 release page: "The DR1 data are released under the Creative Commons Attribution 4.0 International License (CC BY 4.0)."
  - `download.sh` re-checks the statement on every run.
- Attribution: cite the DR1 paper and include the DESI acknowledgment text. The only change is the byte order.
- Access: anonymous HTTPS byte-range GETs. The script accepts only HTTP 206 responses and caps response size.

## Shape and conversion

- **Selection:** 36 evenly spaced healpix groups. In each group, the lowest-numbered healpix whose coadd file is 100–250 MB (250–544 targets) is taken.
- **Download:** only the primary header and the three FLUX header+data ranges are fetched; IVAR, MASK, RESOLUTION, WAVELENGTH, FIBERMAP and SCORES are never fetched.
  - Range bytes: 459,879,928.
  - Of these, 459,303,928 are primary data, so more than 99.8% of downloaded bytes are kept.
- **Natural record:** one FLUX image HDU, as DESI distributes it.
  - Rows are targets in FIBERMAP order; columns are wavelength pixels.
  - Even single-target rows would clear the 1,000-value floor, so the HDU sample is not a floor-driven concatenation.
- **Conversion:** FITS BITPIX −32, with no BSCALE or BZERO, is byte-swapped from big-endian to little-endian. Every bit pattern is preserved, and there is no FITS padding.
- **Missing values:** DESI writes 0 for fully masked coadd pixels. These zeros are kept. An HDU is fatal if it has more than 35% all-zero rows, any non-finite value, or a constant value.

## Accepted output

- Files: 36 (36 distinct groups, healpix 5..49100)
- Targets per arm: 14,429
- Primary samples: 108 (36 per arm)
- Primary values: 114,825,982 (B 39,694,179; R 33,561,854; Z 41,569,949)
- Primary bytes: 459,303,928 (B 158,776,716; R 134,247,416; Z 166,279,796)
- Sample size: minimum 581,500 values, median 1,081,590, maximum 1,567,264
- Zero values: 1.98% overall
- All-zero target rows: B 171, R 310, Z 208
- Worst HDU: healpix 49100 R_FLUX, with 115 of 398 rows all zero, as one contiguous block, rows 44–147. This fits one petal's R camera having no data. Every other HDU has at most 7% all-zero rows.
- Value range: −3231.6 to 7247.4. Medians are about 0.2–0.3 ×1e-17 erg/s/cm²/Å.

## Judge checks

- **Gate:** `gate.py` passes with no warnings.
- **Verify:** I re-ran `verify.sh`: `verify_ok`, 36 files, 108 samples, 459,303,928 bytes, 24.4 s, 198 MB RSS.
  - The earlier 19:04 failure log stops mid-run, which points to an outside interrupt. Later runs passed.
  - `build.sh` and `verify.sh` read only local range files and make no network calls.
- **Live bytes:** I fetched a 4 KB HTTP 206 range of `coadd-main-dark-21777.fits` Z_FLUX, starting at row 100. Decoded as big-endian float32, it is bit-identical to the built little-endian sample.
  - The live header shows XTENSION IMAGE, BITPIX −32, NAXIS1 2881, NAXIS2 250, EXTNAME Z_FLUX, BUNIT `10**-17 erg/(s cm2 Angstrom)`, a DATASUM card, and no scaling.
- **Value statistics (18 samples, 6 healpix × 3 arms):**
  - 17–33% of values are negative, from sky-subtraction noise.
  - 92–99% of values are distinct float32.
  - All 256 low-mantissa byte values occur, and the exponents spread over 2^-4..2^0, so the width is honest.
- **Duplicates:** I hashed every row of all 108 samples: 0 duplicates among 42,598 nonzero rows.
- **Zero structure:** most all-zero rows recur at the same indices in all three arms, meaning targets with no good data in any arm. The single large dropout (49100 R) is contiguous and confined to one arm.
- **Novelty:** `novelty.py` finds no DESI, SDSS-spectra, LAMOST, APOGEE or GALAH material locally or downstream. There is no match for the instrument line or archive.
- **Rights:** I read the CC BY 4.0 statement in the downloaded license page and on the live DR1 release page. No scripts contain credentials, and the data contain no personal information.
- **Homogeneity:** one survey and program (main/dark), one production (iron), one unit, and continuous float32. The three arms are kept as separate series.
- **Caveat (not a defect):** the 100–250 MB size band leaves out the densest healpix fields. Coverage still spans the sky from healpix 5 to 49100, and the band does not change the flux regime.
