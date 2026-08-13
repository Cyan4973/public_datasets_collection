# Poly Haven HDRI OpenEXR Float32 Planes

Nine native float32 RGB radiance planes from three CC0 Poly Haven HDRIs:

| Source | Shape | Compression | Retained planes |
|---|---:|---|---:|
| `abandoned_greenhouse_1k.exr` | 512x1024 | ZIP | RGB |
| `ph_golden_gate_hills_4k.exr` | 2048x4096 | ZIP | RGB |
| `ph_brown_photostudio_02_8k.exr` | 4096x8192 | PIZ | RGB |

The latter two are the public samples listed by
`aras-p/test_exr_htj2k_jxl`; their MD5s exactly match the corresponding
official Poly Haven API objects. Constant alpha channels, where present, are
excluded. The resulting nine samples contain 127,401,984 values and
509,607,936 bytes.

The recipe pins TinyEXR v1.0.12 and compiles its single header against system
zlib. It keeps source FLOAT bit patterns, supports the required PIZ and ZIP
compression, and writes canonical little-endian output. Verification decodes
all three EXRs again and compares every output byte.

Run:

```bash
bash datasets/polyhaven_hdri_exr_f32/download.sh
bash datasets/polyhaven_hdri_exr_f32/build.sh
bash datasets/polyhaven_hdri_exr_f32/verify.sh
```

License: CC0 1.0 Universal.
