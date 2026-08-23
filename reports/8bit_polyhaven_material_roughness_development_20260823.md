# Poly Haven Material Roughness Uint8 — 2026-08-23

## Outcome

`polyhaven_material_roughness_u8` adds eight CC0 PBR material-roughness maps
covering painted wood, concrete, wallpaper, stone, rusted metal, bark, sand,
and denim. Each material is one independent 1024×1024 uint8 plane, totaling
8,388,608 values and bytes.

This is a new semantic field even though it deliberately reuses the eight
material subjects in `polyhaven_material_displacement_png_u16`. Displacement
is a 16-bit mesoscopic height field; roughness is an 8-bit microsurface
scattering field with different value ranges and spatial behavior.

## Source choice and rights

Poly Haven publishes the assets under CC0 1.0. Its official API exposes both
16-bit PNG and 8-bit JPEG roughness products. The lossless PNGs were inspected
first and rejected for this width because seven are grayscale16 and one is
RGB16. The accepted recipe instead uses Poly Haven's separately published 1K
JPEG delivery products; it does not reduce the PNG samples to eight bits.

The exact eight JPEG URLs, sizes, and provider MD5 values are tracked in
`sources.tsv`. The downloader validates them against the live official API and
checks the official CC0 page. Their aggregate compressed size is 3,620,047
bytes.

## Typed decoding

Seven JPEGs declare one 8-bit component. `concrete_wall_008` declares three,
but deterministic RGB decoding found R=G=B at every one of its 1,048,576
pixels. The recipe enforces that equality before retaining the common byte;
it never projects colored pixels to luma.

The eight planes contain 18 to 180 distinct byte values. Several materials
occupy intentionally narrow roughness ranges, but all remain strongly spatial:
each has more than 698,000 adjacent-value transitions and no dominant value
exceeds 35% of its plane. The acceptance checks therefore retain narrow valid
fields while rejecting fewer than eight values, more than 99% dominance,
fewer than 10,000 transitions, or duplicate decoded planes.

## Verification

The user-run downloader and local build and verification passed on 2026-08-23.
Verification rechecks the pinned source sizes and MD5 identities, reparses JPEG
geometry and precision, repeats deterministic single-threaded FFmpeg decoding,
rechecks achromaticity and distributions, and byte-compares all generated
planes with fresh source decoding. Every output is raw row-major uint8; byte
order is inherently endian-independent and recorded as little-endian for the
corpus contract.
