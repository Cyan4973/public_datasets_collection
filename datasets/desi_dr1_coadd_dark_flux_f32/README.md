# DESI DR1 main-survey dark-program coadded flux, B/R/Z arms, float32

This recipe collects calibrated, coadded optical spectra of faint
extragalactic targets (luminous red galaxies, emission-line galaxies and
quasars) from the Dark Energy Spectroscopic Instrument (DESI) Data Release 1,
spectroscopic production `iron`. Only the main survey's dark-time program is
used (`healpix/main/dark/`). Bright, backup, SV and CMX programs are excluded
because their flux regimes and target populations differ.

## Material

Each DESI healpix coadd FITS file (`coadd-main-dark-<HEALPIX>.fits`, nside 64,
nested) stores, per spectrograph arm, a `<ARM>_FLUX` IMAGE HDU with
`NTARGET x NWAVE` big-endian float32 values (`BITPIX = -32`,
`BUNIT = '10**-17 erg/(s cm2 Angstrom)'`). The arms have fixed wavelength
grids, 0.8 Angstrom per pixel:

| arm | NWAVE | range |
| --- | --- | --- |
| B | 2751 | 3600-5800 Angstrom |
| R | 2326 | 5760-7620 Angstrom |
| Z | 2881 | 7520-9824 Angstrom |

The three arms are three primary series (`desi_coadd_b_flux_f32`,
`desi_coadd_r_flux_f32`, `desi_coadd_z_flux_f32`). They share a unit, but
their noise levels, throughput and sky-line residuals differ, so they are not
mixed. One sample is one complete FLUX image HDU of one coadd file. This is
the array DESI distributes, and its rows follow the order of the file's
`FIBERMAP` table, one row per target. Rows are never dropped or reordered,
and FITS block padding is not included.

The recipe keeps no IVAR, MASK, RESOLUTION, WAVELENGTH, FIBERMAP or redshift
data. The wavelength grid of each arm is fixed and documented above.

## Scope and selection

`pinned_hdus.tsv` was produced by `discover.sh`, which makes metadata-only
requests (directory listings, HEADs and header range GETs). It lists the DR1
`healpix/main/dark` groups (223 groups, group = healpix // 100), takes 36
evenly spaced groups, and picks the lowest-numbered healpix in each whose
coadd file is 100-250 MB. This size band corresponds to roughly 220-560
targets. If a group has no file in the band, the next group is used. The size
band keeps the whole pull to a few hundred MB, because full files can reach
860 MB (about 1,900 targets). Every HDU header of each selected file was
walked to pin:

- the header offset and length of each FLUX HDU
- the header SHA-256
- the shape (NAXIS1, NAXIS2)
- the data-unit length (NAXIS1 * NAXIS2 * 4)
- the FITS `DATASUM` card

## Download

`download.sh` performs these steps:

1. It re-checks the CC BY 4.0 statement on the DESI license page.
2. For each pinned file, it confirms the live `Content-Length` and
   `Last-Modified` and fetches the primary header. It then checks the header's
   SHA-256 and that `SURVEY=main`, `PROGRAM=dark` and `HPXPIXEL`.
3. It fetches one contiguous range per arm: the FLUX extension header plus
   the unpadded data unit.

Each range is checked for exact size, header SHA-256, `EXTNAME`, `BUNIT`,
`BITPIX=-32`, `NAXIS1` in {2751, 2326, 2881} and the pinned `NAXIS2`. The
32-bit ones'-complement FITS `DATASUM` is recomputed over the fetched data
unit. Zero padding does not change that sum, so every range is checked
end-to-end even though the per-directory `sha256sum` files only cover whole
files. Transfers resume from the bytes already on disk. They are bounded by
stall detection (`--speed-limit 1024 --speed-time 120`) rather than wall
time, and any response other than HTTP 206 is refused.

## Build and verify

`build.sh` re-validates every range, then byte-swaps the big-endian float32
data unit to little-endian with no value change. It writes:

- one file per HDU: `samples/<id>/<series>/coadd-main-dark-<HEALPIX>_<ARM>_FLUX.f32le`
- the index `index/<id>/samples.jsonl`, with the standard fields plus
  `sample_shape = [NTARGET, NWAVE]`, healpix, source offset and DATASUM,
  stored-float32 min/max, all-zero row count and SHA-256

Missing-value policy:

- DESI marks fully masked coadd pixels with flux 0 (and IVAR 0). These zeros
  are source values and are kept.
- A target whose entire row is zero is kept in place and counted.
- An HDU with more than 35% all-zero rows, any non-finite value, or a
  constant value is rejected.

Realized build: 36 files from 36 distinct groups, 14,429 targets per arm, 108
samples, 114,825,982 float32 values, 459,303,928 bytes. The median sample has
1,081,590 values. Zeros are 1.98% of all values. All-zero target rows total
171 (B), 310 (R) and 208 (Z) out of 14,429 per arm. The worst HDU is
healpix 49100 R_FLUX, with 115 of 398 rows all zero (29.7% of values), which
is consistent with an R camera that recorded no data for part of that
healpix's exposures. It is kept because it is the natural record, and the
35% limit was set with this case in view. Every other HDU stays at or below
7% zero values.

`verify.sh` re-parses each header with a separate fixed-column reader and
recomputes `DATASUM`. It decodes the data unit independently with
`struct.unpack('>f')` and byte-compares the result with each sample. It also
checks:

- the index fields, min/max, zero-row counts and uniqueness of every sample
- that each sample is non-constant, at least 50% nonzero, and has at least
  1,000 distinct values in its first 200,000
- that all three arms cover the same healpix set
- the manifest's `sample_count` and `total_size_bytes`

## License

DESI data are licensed under CC BY 4.0
(<https://data.desi.lbl.gov/doc/acknowledgments/>): "The Dark Energy
Spectroscopic Instrument (DESI) data are licensed under the Creative Commons
Attribution 4.0 International License". The DR1 release page states: "The
DR1 data are released under the Creative Commons Attribution 4.0
International License (CC BY 4.0)."

Attribution requires citing DESI Collaboration et al., "Data Release 1 of the
Dark Energy Spectroscopic Instrument", and including the DESI acknowledgment
text from that page. These samples are a format conversion (FITS big-endian
to raw little-endian), with no change to any value.

## Run

```bash
bash staging/desi_dr1_coadd_dark_flux_f32/download.sh
bash staging/desi_dr1_coadd_dark_flux_f32/build.sh
bash staging/desi_dr1_coadd_dark_flux_f32/verify.sh
```
