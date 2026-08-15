# Aras Blender OpenEXR evaluation suite

Evaluation-only suite for the eight Blender-generated OpenEXR files listed
by `aras-p/test_exr_htj2k_jxl`. The files are publicly downloadable and were
used as lossless floating-point image compression benchmarks, but no explicit
license covering these external payloads was located.

This suite must therefore remain isolated from training:

- intended use: evaluation only;
- training eligible: false;
- redistribution authorized: false;
- rights status: unclear.

The two linked Poly Haven EXRs are deliberately excluded because their
byte-identical CC0 originals are already accepted by
`datasets/polyhaven_hdri_exr_f32`.

Acquire the eight hash-pinned files (about 1.55 GB):

```bash
bash evaluation/aras_blender_openexr_eval/download.sh
```

The downloader supports partial-file resume and validates every completed
payload by pinned size, MD5, and SHA-256.

Build and verify:

```bash
bash evaluation/aras_blender_openexr_eval/build.sh
bash evaluation/aras_blender_openexr_eval/verify.sh
```

The realized material contains 121 complete 3840x2160 channel planes:

- 77 native IEEE-754 binary16 planes: 638,668,800 values / 1,277,337,600 bytes;
- 44 native IEEE-754 binary32 planes: 364,953,600 values / 1,459,814,400 bytes;
- 121 planes / 1,003,622,400 values / 2,737,152,000 bytes total.

Ten all-one alpha planes remain registered for completeness but declare
`benchmark_eligible = false`; the other 111 planes are benchmark-eligible.
Every plane is finite. All outputs preserve native HALF/FLOAT bit patterns and
use canonical little-endian byte order.
