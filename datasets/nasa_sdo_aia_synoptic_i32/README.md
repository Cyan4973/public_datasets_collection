# NASA SDO/AIA Synoptic Int32 — Discovery

This staged candidate targets Solar Dynamics Observatory Atmospheric Imaging
Assembly (SDO/AIA) synoptic images from the official JSOC archive. It is the
width-correct successor to the rejected int16 attempt: bounded FITS-header
inspection established that these products are tiled-compressed logical
`ZBITPIX=32` images with `BSCALE=0.0625` and `BZERO=0`.

The intended sample is one complete `1024 × 1024` signed-int32 solar image at
each of AIA's ten synoptic wavelength channels. After lossless FITS tile
decompression, the stored integer codes will be converted from FITS big-endian
order to raw little-endian int32. The physical-value relation
`value = stored_code × 0.0625` remains metadata; the recipe will not widen the
pixels to float64.

The discovery step deliberately selects a fixed historical month rather than
the mutable `mostrecent/` directory. It traverses bounded official JSOC
directory listings, range-reads FITS headers only, and requires one fixed-hour
directory covering all ten wavelengths with identical geometry and scaling.
Because the channels have different cadences, it selects the earliest exposure
for each wavelength within that hour rather than requiring an impossible exact
timestamp match. It also captures the official SDO data-access and copyright
pages plus NASA reuse guidelines before any image payload is downloaded.

Run from the repository root:

```bash
bash staging/nasa_sdo_aia_synoptic_i32/discover.sh
```

Results are written under `.data/discovery/nasa_sdo_aia_synoptic_i32/` and the
durable log under `.data/logs/nasa_sdo_aia_synoptic_i32/`.

The metadata and rights preflight selected the stable archive directory
`2025/01/01/H0000/`. Nine wavelength planes use the 00:00 exposure; the 1700 Å
channel uses its earliest available exposure at 00:02 because AIA channel
cadences differ.

The next step downloads those ten FITS files and the latest stable versioned
CFITSIO source tarball from NASA HEASARC:

```bash
bash staging/nasa_sdo_aia_synoptic_i32/download.sh
```

After acquisition, `build_tool.sh` performs only a conventional local
`configure` plus `make funpack`. CFITSIO 4.7.0 built successfully with the
existing C toolchain and zlib, without installing packages or system files.
The selected FITS headers identify SDO/AIA and carry no contrary copyright
notice. The pinned SDO page says SDO images and movies are not copyrighted
unless explicitly noted; NASA's general guidance allows factual reuse with
attribution and without implying endorsement.

Build and verify the numeric samples with:

```bash
bash staging/nasa_sdo_aia_synoptic_i32/build.sh
bash staging/nasa_sdo_aia_synoptic_i32/verify.sh
```
