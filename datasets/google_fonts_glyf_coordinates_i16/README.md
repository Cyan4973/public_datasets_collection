# Google Fonts TrueType Glyph Coordinates Int16

This candidate targets vector-font geometry: reconstructed signed-16-bit
design-unit coordinates from TrueType `glyf` contours. It is distinct from
text/code-unit streams and from triangle-mesh index arrays.

The recipe pins an exact commit of the official `google/fonts` repository and
three families from its Apache-licensed collection. A strict dependency-free
parser validates the SFNT directory and `head`, `maxp`, `loca`, and `glyf`
tables, decodes all simple-glyph flags and x/y deltas, reconstructs absolute
coordinates, and checks declared glyph bounds.

Run:

```bash
bash datasets/google_fonts_glyf_coordinates_i16/download.sh
bash datasets/google_fonts_glyf_coordinates_i16/inspect.sh
bash datasets/google_fonts_glyf_coordinates_i16/build.sh
bash datasets/google_fonts_glyf_coordinates_i16/verify.sh
```

Composite glyphs are inventoried but are not expanded because expansion would
duplicate referenced outlines.

## Selected fonts

At Google Fonts commit
`2796410152d4f9524b68ed46e69c1b60f8e0f7c3`, three Apache-2.0 families
qualified:

- Aclonica Regular: 203 simple glyphs, 14,634 coordinate values
- Roboto Slab variable: 483 simple glyphs, 30,950 coordinate values
- Special Elite Regular: 202 simple glyphs, 98,058 coordinate values

The output is one font-level row-major `[point, xy]` int16 sample per
font. Simple glyphs remain in glyph-index order; composite glyphs are excluded
to avoid duplicating referenced contours.
