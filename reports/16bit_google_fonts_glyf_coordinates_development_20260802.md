# Google Fonts TrueType Glyph Coordinates Int16 Development — 2026-08-02

`google_fonts_glyf_coordinates_i16` adds a new 16-bit domain: vector
typography geometry reconstructed from TrueType glyph contours.

## Source and license

The recipe pins Google Fonts commit
`2796410152d4f9524b68ed46e69c1b60f8e0f7c3` and three families from its
Apache-licensed collection: Aclonica, Roboto Slab, and Special Elite. Each TTF
is pinned by file size, SHA-256, and Git blob SHA. Each family supplies the
same complete 11,358-byte Apache License 2.0 text, also pinned by SHA-256.

## TrueType decoding

The dependency-free parser validates the SFNT table directory and the
`head`, `maxp`, `loca`, and `glyf` tables. For every nonempty simple glyph it:

- validates contour endpoint indices and instruction bounds;
- expands repeated point flags;
- decodes TrueType's short, same/zero, and signed-16 delta forms;
- reconstructs absolute x/y design-unit coordinates;
- requires every coordinate to fit signed int16; and
- compares reconstructed extrema with the glyph's declared bounding box.

Points are emitted in glyph-index and within-glyph point order, interleaved as
x/y pairs. Composite glyphs are counted but not expanded because they reuse
and transform simple glyphs; expanding them would duplicate outline material.
Empty glyphs contribute no coordinates.

## Quality assessment and verified output

The accepted family contains:

- primary samples: `3` (one per font)
- simple glyphs: `888`
- simple contours: `1,507`
- outline points: `71,821`
- primary int16 values: `143,642`
- primary bytes: `287,284`
- distinct coordinate values per font: `1,892` to `2,432`
- overall observed coordinate range: `-659` to `2,408`

Special Elite contributes unusually dense distressed/typewriter outlines,
while Aclonica and Roboto Slab supply cleaner display and slab-serif geometry.
This creates materially different local contour patterns within one coherent
representation.

The concatenated decoded payload SHA-256 in manifest source order is
`442c8aabdc2ea8eceeffcb837f32f1d952e976f55ed2335e37af9c4526d85e97`.
Build and verification passed. Verification rechecks source and license
identities, fully redecodes every simple glyph, enforces glyph-boundary and
payload hashes/statistics, and byte-compares all emitted font samples with
fresh decodes.
