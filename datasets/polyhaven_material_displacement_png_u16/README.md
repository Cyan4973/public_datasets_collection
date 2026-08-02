# Poly Haven Material Displacement UInt16

This candidate adds a computer-graphics/material-height family: eight CC0
Poly Haven displacement maps stored as native 16-bit grayscale PNG images.
The bounded selection covers painted wood, concrete, wallpaper, stone, rusted
metal, bark, sand, and denim without duplicating the corresponding 2K maps.

Every source is 1024×1024. The intended output is eight independent row-major
little-endian uint16 planes: 8,388,608 values and 16,777,216 decoded bytes.
PNG filtering and zlib compression are removed; no color conversion,
normalization, quantization, or resampling is performed.

Poly Haven states that all assets are released under CC0:
<https://polyhaven.com/license>

Run:

```bash
bash datasets/polyhaven_material_displacement_png_u16/download.sh
bash datasets/polyhaven_material_displacement_png_u16/inspect.sh
bash datasets/polyhaven_material_displacement_png_u16/build.sh
bash datasets/polyhaven_material_displacement_png_u16/verify.sh
```

The downloader pins every object by byte size and MD5. The decoder validates
PNG chunk CRCs, requires a non-interlaced scalar grayscale16 image, reverses
all five standard PNG row filters, and converts PNG's big-endian samples to
the corpus's little-endian uint16 representation.
