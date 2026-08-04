# IMAT neutron-tomography float32 development — 2026-08-04

## Outcome

Accepted `zenodo_imat_neutron_projections_f32` as a width-correct successor to
the unsuccessful `zenodo_neutron_tomography_u16` search.

The source is Zenodo record `4273969`, *Neutron tomography data of high-purity
metal rods using golden-ratio angular acquisition (IMAT, ISIS)*, DOI
`10.5281/zenodo.4273969`, explicitly released under CC BY 4.0.

## Why the 16-bit search changed width

The initial broad search found two direct TIFFs in record `10695600`; full-file
inspection proved both were RGB renderings with `BitsPerSample=[8,8,8]`. A
bounded neutron-radiography archive, `exp101.zip` in record `17418255`, held 20
genuine detector frames but stored them as float64 FITS (`BITPIX=-64`).

The IMAT archive is scientifically and structurally suitable, but all 186 TIFF
projections declare `BitsPerSample=32`, `SampleFormat=3` (IEEE floating point),
one channel, and no TIFF compression. Reinterpreting or quantizing them as
16-bit would violate native-width collection policy, so the candidate was
promoted as float32 instead.

## Accepted material

- 186 complete angular projection frames, `proj_0000.tiff` through
  `proj_0185.tiff`
- fixed shape `512 x 512`
- 48,758,784 native float32 values
- 195,035,136 decoded numeric bytes
- 186 distinct payload hashes
- all values finite; global range `0.0` through `2154.28515625`
- at least 252,842 distinct values in every frame
- 4,258 zero values overall
- per-frame zlib-9 ratios from about 0.860 to 0.869, median about 0.866

Each output is one natural detector frame. The acquisition index and
golden-ratio angle are retained in the sample index. The TIFF pixel strip is
already little-endian float32 and is copied byte-for-byte; ZIP and TIFF framing
are not training material.

## Reproducibility and safety

The recipe pins archive size `168192038` and MD5
`9abc2df64fdf58cb4e194cbf29131b27`, validates record identity and CC BY 4.0,
requires the exact 186-frame member set and scan metadata, checks every TIFF
layout and every numeric value, and independently re-decodes each source member
during verification. This is physical detector data for a metal-rod phantom
and contains no personal or human-subject information.
