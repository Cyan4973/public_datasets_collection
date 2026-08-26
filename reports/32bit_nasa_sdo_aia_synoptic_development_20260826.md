# NASA SDO/AIA Synoptic Int32 Images — 2026-08-26

## Outcome

Accepted `nasa_sdo_aia_synoptic_i32`: ten complete `1024 × 1024` signed-int32
solar image planes spanning all SDO/AIA synoptic wavelength channels.

The recipe contributes 10,485,760 values and 41,943,040 primary bytes. Every
sample has the same two-dimensional geometry.

This is the width-correct successor to the rejected
`nasa_sdo_aia_synoptic_fits_i16` attempt. That earlier header investigation was
not wasted: it established that the products are tiled-compressed logical
`ZBITPIX=32` images rather than int16 images.

## New domain and shape

The family adds signed-int32 solar EUV/UV imagery. Existing FITS coverage
contains float32 astronomical cubes, while other accepted 32-bit raster-like
families contain float32 radar, tomography, ultrasound, or HDR radiance and
uint32 identifiers or dose. These SDO products instead contain spatially
correlated fixed-point solar-intensity codes in complete 2D planes.

The selection uses the stable historical JSOC directory
`2025/01/01/H0000/`, never the mutable `mostrecent/` path. AIA channel cadences
differ, so the deterministic rule chooses the earliest qualifying exposure per
wavelength in that hour: nine images are from approximately 00:00 UTC and the
1700 Å image is from 00:02 UTC.

## Source and rights

The ten exact official JSOC FITS files total 10,581,120 compressed bytes and
are pinned individually by size and SHA-256 in `selection.tsv`. Their headers
identify `ORIGIN=SDO`, `TELESCOP=SDO`, and the relevant AIA instrument channel;
none carries a contrary copyright field.

The pinned official SDO copyright page states that SDO images and movies are
not copyrighted unless explicitly noted and requests attribution to NASA/SDO
and the AIA, EVE, and HMI science teams. The pinned NASA media guidelines state
that NASA content is generally not subject to copyright in the United States
and permit factual use subject to attribution and non-endorsement constraints.
The numeric samples contain no logo, person, or endorsement material.

## Decoding and representation

Every source is a FITS tiled-image binary-table extension declaring:

- `ZCMPTYPE=RICE_1`;
- `ZBITPIX=32`;
- `ZNAXIS=2`, `ZNAXIS1=1024`, and `ZNAXIS2=1024`;
- `BSCALE=0.0625` and `BZERO=0`.

The official CFITSIO 4.7.0 source archive is pinned by SHA-256. Its standard
`configure --disable-shared` and `make funpack` build completed in roughly 24
seconds using the existing C compiler and zlib, without package installation or
a dependency stack. `funpack` losslessly reconstructs an ordinary FITS
`BITPIX=32` image while retaining `BSCALE` and `BZERO`.

The recipe extracts the reconstructed big-endian signed-int32 stored codes and
writes them in canonical little-endian order. The scale remains metadata:
physical intensity equals `stored_code × 0.0625`. No widening or numeric
rounding occurs.

## Verification

All ten images contain exactly 1,048,576 pixels, no FITS `BLANK` values, and
nonconstant, mutually distinct payloads. Independent verification reruns
CFITSIO decompression, validates the pinned source identities and rights pages,
checks the decoded FITS headers and padding, and compares every little-endian
output byte with a fresh conversion.
