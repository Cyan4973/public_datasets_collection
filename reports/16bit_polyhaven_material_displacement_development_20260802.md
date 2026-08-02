# Poly Haven Material Displacement UInt16 Development — 2026-08-02

`polyhaven_material_displacement_png_u16` adds a new 16-bit domain:
computer-graphics material displacement/height fields used by physically based
renderers to synthesize surface geometry.

## Source and license

Poly Haven publishes all of its assets under CC0 1.0. The bounded selection
uses eight exact 1K displacement PNGs covering painted wood, concrete,
wallpaper, stone, rusted metal, bark, sand, and denim. Each object is pinned by
its direct URL, byte size, and MD5. Corresponding 2K versions were excluded to
avoid near-duplicate resolutions of the same fields.

## Native representation and decoding

Every source declares a 1024×1024, color-type-0 grayscale PNG with a native
bit depth of 16. The strict decoder validates every chunk CRC, the PNG chunk
sequence, contiguous IDAT data, the complete zlib stream, scanline sizes, and
filter types. It reverses PNG filters 0–4 bytewise and converts the
reconstructed big-endian uint16 words to little-endian without changing their
values. There is no color conversion, resampling, normalization, or
quantization.

## Quality assessment and verified output

The accepted family contains:

- primary samples: `8`
- primary values: `8,388,608`
- primary bytes: `16,777,216`
- distinct values per map: `7,081` to `45,464`
- flattened transitions per map: `1,018,468` to `1,048,483`
- zero values across every map: `0`
- saturated values across every map: `0`

The maps have materially different ranges and spatial structures while
sharing fixed geometry, making them a coherent compression-training family
rather than arbitrary image fragments. The concatenated decoded payload
SHA-256 in source order is
`7b5fae02a47cb2926a5b58f7ac92f9650eb0b9c36f9d6a743a11c18f9673b1a3`.

Build and verification passed. Verification rechecks all source identities,
strictly redecodes every PNG, enforces each decoded SHA-256 and measured value
statistics, and byte-compares all eight emitted planes against fresh decodes.
