# NASA PDS Mastcam-Z raw int16 development — 2026-08-08

## Outcome

Accepted `nasa_pds_mastcamz_raw_i16`: 52 complete native signed-int16
Mastcam-Z Experiment Data Record detector frames from the first two sols of
the Mars 2020 Perseverance mission.

## Domain value and overlap

This adds rover-camera detector imagery with optical-filter and hardware-
companding structure. Existing NASA PDS families cover MOLA topography,
THEMIS infrared mosaic bytes, and SHARAD radargrams; none is a Mastcam-Z raw
visible/near-infrared detector plane. The natural sample is a complete
`1200 x 1648` camera frame, not a tile or generic decoded photograph.

## Discovery and selection

Bounded metadata-only discovery traversed the official PDS Imaging sol-1 and
sol-2 prefix, inspecting directory listings, PDS4 XML labels, and HTTP size
metadata without acquiring image payloads. It found 52 complete two-
dimensional EDR products whose labels declare `SignedMSB2`, a fixed array
offset of 32,960 bytes, and `1200 x 1648` geometry. Non-EDR products,
unsigned-byte images, and three-band arrays were excluded.

The accepted plan includes all 52 qualifying products: 27 left-camera and 25
right-camera frames spanning multiple Mastcam-Z filters. Exact label and IMG
identities are pinned in `sources.tsv` and `payloads.sha256`.

## Accepted material

- 52 natural complete two-dimensional frame samples
- 1,977,600 signed-int16 values and 3,955,200 bytes per sample
- 102,835,200 values and 205,670,400 primary bytes total
- observed stored range: 0 through 2,033
- 82,990,984 adjacent-pixel value transitions in aggregate
- 15 through 254 distinct stored values per frame
- 27,663 zero values in aggregate

The PDS labels declare 12 significant sample bits and the mask
`2#0000111111111111#`. They also identify hardware companding with
`MCZ_LUT0` or `MCZ_LUT1` in expanded form. Consequently, some valid frames
occupy a sparse set of DN codes despite having substantial spatial variation;
the recipe validates both the metadata and the observed non-degeneracy.

## Identity and conversion

Every source label SHA-256 and IMG SHA-256 is pinned. The downloader rejects
changed product identities, sizes, schemas, or hashes. The build extracts only
the complete declared `Array_2D_Image` from each IMG and reverses each
big-endian word to the repository's canonical little-endian signed-int16
representation. It performs no arithmetic conversion, decompanding,
calibration, crop, resampling, splitting, or concatenation.

Independent verification decodes all 52 source arrays again and compares the
resulting bytes, sample index, statistics, and hashes against the built
outputs. All checks passed.

## License and safety

The products are public NASA mission observations served by the official NASA
PDS Imaging archive. NASA SMD's science-information policy states that
SMD-funded scientific information is held as a public trust, made publicly
available, and openly shared. The recipe retains mission, instrument, product,
and PDS attribution. Samples contain only robotic camera detector values from
Mars; PDS/VICAR headers are excluded, and there is no personal or sensitive
content.
