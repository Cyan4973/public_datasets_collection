# Poly Haven HDRI OpenEXR Float32 TinyEXR Expansion — 2026-08-13

## Outcome

`polyhaven_hdri_exr_f32` was expanded from one 1k HDRI and four channel
outputs to three pinned HDRIs and nine nonconstant RGB channel planes. The
promoted family contains 127,401,984 native float32 values and 509,607,936
bytes.

The earlier custom decoder handled only ZIP and accidentally admitted a
constant alpha plane. The promoted recipe uses pinned TinyEXR v1.0.12, handles
both ZIP and PIZ, and explicitly excludes constant channels.

## Source and license evidence

Poly Haven's official license page states that all assets are CC0, may be used
for any purpose including commercial work, need no attribution, and may be
redistributed.

| Source | Compressed bytes | MD5 | SHA-256 |
|---|---:|---|---|
| `abandoned_greenhouse_1k.exr` | 6,115,125 | `b190c4a06d12ee0b641cfe6053aa6056` | `3ff5b53e171333ad410f8c0b7f491d0c3f3bd25a01b6d3f1262b710389a96d64` |
| `ph_brown_photostudio_02_8k.exr` | 77,556,275 | `ea9d4aebdc6ab119c99daea63e547900` | `a1c7a7edf1bfb9cb7f9a252e7281f2f10767befdb9cb6c6a28209730a46e9642` |
| `ph_golden_gate_hills_4k.exr` | 96,436,466 | `7fbc8ea1646f59ef5cd0b202a4359cb6` | `e0d76ca478552cef5f6b03e40be4943a1f4a4908ba17e308e9598f802681215f` |

The two large files were selected from the public
`aras-p/test_exr_htj2k_jxl` comparison list. Their MD5s exactly match the 8k
and 4k objects returned by the official Poly Haven API, establishing that the
mirror copies are byte-identical to the CC0 originals. The accepted downloader
prefers the official Poly Haven URLs and retains the comparison URLs only as
fallbacks.

## Decoder

TinyEXR v1.0.12 is pinned at 299,406 bytes and SHA-256
`e3eb50490af81dc3f5f067cf7f62955894d5db8f88a091c19bc4eef8e468095f`.
Its single header contains the BSD license notices. It compiles directly with
the system C++ compiler and zlib; no package manager, Conda environment, or
large dependency tree is required.

The wrapper requires OpenEXR v2, single-part non-deep scanline images,
full-resolution FLOAT channels, and supported lossless compression. It leaves
TinyEXR's requested channel types equal to the source FLOAT type, rejects any
non-finite retained value, skips constant channels, and writes canonical
little-endian float32 words.

## Decoded material

| Source | Geometry | Compression | Retained channels | Values | Bytes |
|---|---:|---|---|---:|---:|
| abandoned greenhouse | 512x1024 | ZIP | B, G, R | 1,572,864 | 6,291,456 |
| brown photostudio | 4096x8192 | PIZ | B, G, R | 100,663,296 | 402,653,184 |
| golden gate hills | 2048x4096 | ZIP | B, G, R | 25,165,824 | 100,663,296 |
| **Total** | | | **9 samples** | **127,401,984** | **509,607,936** |

The abandoned-greenhouse and golden-gate alpha planes are exactly constant and
are excluded. Brown Photostudio exposes RGB only. All nine retained planes are
finite and nonconstant. Their median natural sample is 8,388,608 values and
33,554,432 bytes.

## Verification

`build.sh` validates every EXR and the TinyEXR source by size, MD5, and
SHA-256 before decoding. It enforces exact source geometry, channel inventory,
compression, aggregate counts, and output hashes. `verify.sh` then decodes all
three EXRs afresh into a temporary directory and compares all nine planes
byte-for-byte with the accepted outputs.

Both the promoted build and verification completed successfully on
2026-08-13.
