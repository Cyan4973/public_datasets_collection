# Poly Haven HDRI EXR Float32

Collects Poly Haven CC0 HDRI EXR files and emits native float32 channel planes.

Previous attempt targeted f16 HALF but Poly Haven 1k assets are actually 32-bit FLOAT with PIZ/ZIP compression. This reclassifies them as f32, per policy that 32-bit material should not be discarded but reclassified.

```bash
bash staging/polyhaven_hdri_exr_f32/download.sh
bash staging/polyhaven_hdri_exr_f32/build.sh
bash staging/polyhaven_hdri_exr_f32/verify.sh
```

Parser supports ZIP (zlib) compressed FLOAT scanline EXR, skips PIZ for now. One ZIP file yields 4 channel samples (e.g., 1024x512 float32).

License: CC0 1.0
