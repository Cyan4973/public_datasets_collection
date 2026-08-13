# ASWF OpenEXR Scanline HALF Development — 2026-08-13

## Outcome

`aswf_openexr_scanlines_f16` adds a licensed native-float16 computer-graphics
and HDR imaging family. Eight official Academy Software Foundation/OpenEXR
reference images yield 27 complete channel-plane samples containing 22,462,336
IEEE-754 binary16 values and 44,924,672 bytes.

RGB radiance/color and alpha opacity are separate semantic series:

| Series | Samples | Values | Bytes |
|---|---:|---:|---:|
| `aswf_openexr_rgb_half_f16` | 24 | 19,532,736 | 39,065,472 |
| `aswf_openexr_alpha_half_f16` | 3 | 2,929,600 | 5,859,200 |
| **Total** | **27** | **22,462,336** | **44,924,672** |

## License and provenance

The `AcademySoftwareFoundation/openexr-images` root license grants
redistribution and use in source and binary forms with the BSD conditions and
disclaimer. `ScanLines/README.rst` additionally declares
`SPDX-License-Identifier: BSD-3-Clause` and OpenEXR Project contributor
copyright.

Both documents and every selected EXR are pinned by repository path, exact
size, Git blob SHA-1, and SHA-256 in `selection.tsv`. Branch movement therefore
cannot silently change accepted material.

## Source selection

The following single-part, full-resolution scanline images are retained:

| Source | Geometry | Compression | Retained channels |
|---|---:|---|---|
| `Blobbies.exr` | 1040x1040 | ZIP | A, B, G, R |
| `CandleGlass.exr` | 810x1000 | PIZ | A, B, G, R |
| `Carrots.exr` | 400x600 | ZIP | B, G, R |
| `Desk.exr` | 874x644 | PIZ | B, G, R |
| `MtTamWest.exr` | 732x1214 | PIZ | B, G, R |
| `PrismsLenses.exr` | 865x1200 | PIZ | A, B, G, R |
| `StillLife.exr` | 846x1240 | PIZ | B, G, R |
| `Tree.exr` | 906x928 | PIZ | B, G, R |

Five exactly constant alpha planes are excluded. `Blobbies.exr` also contains
a native FLOAT depth channel `Z`; it is excluded from this homogeneous
float16 family without conversion.

The discovery pass also found `Cannon.exr`, whose three channels are native
HALF but whose B44 compression is unsupported by TinyEXR v1.0.12. It is not an
accepted source and is documented as a bounded tooling exclusion rather than
silently decoded through a different representation.

## Decoder and representation

TinyEXR v1.0.12 is pinned at SHA-256
`e3eb50490af81dc3f5f067cf7f62955894d5db8f88a091c19bc4eef8e468095f`
and compiled directly against system zlib. Its requested pixel type is left
equal to each source channel's HALF type. The wrapper rejects subsampling,
unexpected structures, non-finite values, and changed channel inventories;
it copies every retained 16-bit word unchanged except for explicit canonical
little-endian output ordering.

## Verification

The accepted build validates every source, license document, provenance
document, and decoder source before decoding. It enforces exact geometries,
compression methods, channel/status counts, series totals, and output hashes.
Verification then decodes all eight EXRs afresh and compares all 27 outputs
byte-for-byte. Build and verification both passed on 2026-08-13.
