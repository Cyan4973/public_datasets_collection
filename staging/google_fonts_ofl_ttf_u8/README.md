# Google Fonts OFL Font Binaries (uint8)

This staging recipe downloads Open Font License font binaries from the Google
Fonts repository and emits one raw uint8 sample per `.ttf` or `.otf` font file.

The natural sample is the source font binary. The build copies the sfnt/OpenType
bytes unchanged; it does not rasterize glyphs or synthesize numeric features.
