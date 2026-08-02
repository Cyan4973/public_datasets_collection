# Silicon Diffraction Pattern TIFF UInt16 — Preflight

This candidate is a native-uint16 electron backscatter diffraction (EBSD)
detector frame from Zenodo record
`1450892`, *Silicon Single Crystal Diffraction Pattern*, released under
CC BY 4.0.

The exact TIFF declares a 1600×1152 scalar unsigned-16-bit plane stored in 64
lossless PackBits strips. Preflight validates the complete TIFF layout, decodes
each strip independently, and reports detector-value cardinality, range,
zero/saturation rates, and spatial transitions before acceptance.

Run:

```bash
bash datasets/zenodo_silicon_diffraction_tiff_u16/download.sh
bash datasets/zenodo_silicon_diffraction_tiff_u16/inspect.sh
bash datasets/zenodo_silicon_diffraction_tiff_u16/build.sh
bash datasets/zenodo_silicon_diffraction_tiff_u16/verify.sh
```

The accepted output is one row-major 1152×1600 little-endian uint16 detector
plane decoded from all 64 strips. TIFF metadata and PackBits framing are not
emitted.
