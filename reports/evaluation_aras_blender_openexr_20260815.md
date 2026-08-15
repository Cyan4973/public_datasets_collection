# Aras Blender OpenEXR evaluation suite — 2026-08-15

## Outcome

Registered `aras_blender_openexr_eval` as evaluation-only material. It contains
all eight Blender-prefixed OpenEXR files listed by
`aras-p/test_exr_htj2k_jxl`, decoded into one numeric sample per native
channel plane.

This family is explicitly excluded from training and from the accepted recipe
audit. It exists to support frozen-model and frozen-codec compression
measurement only.

## Rights and provenance

The EXRs are publicly linked by Aras Pranckevičius and hosted at
`aras-p.info`, but they are external to the Git repository. No explicit
license covering these Blender payloads was located, and the repository itself
exposes no license. Public availability is therefore not represented as
training or redistribution permission.

The evaluation manifest declares:

- `intended_use = "evaluation_only"`;
- `training_eligible = false`;
- `redistribution_authorized = false`; and
- rights status `unclear`.

Payloads and decoded samples remain under `.data/evaluation/`; the recipe
stores only URLs, source hashes, decoder code, metadata, and instructions.
This registration is not a rights grant, and use remains subject to applicable
law and source terms.

The two Poly Haven EXRs linked by the same comparison page are excluded. Their
mirror bytes were already proven identical to official CC0 Poly Haven sources
and are accepted separately as `polyhaven_hdri_exr_f32` training material.

## Pinned source files

| Source | Compressed bytes | Native channels | SHA-256 |
|---|---:|---:|---|
| `Blender281rgb16.exr` | 27,496,316 | 3 HALF | `e6523e928e5b5544db441c88b949cf120d89b7b207a5eaa4bfb4ca8ea5d9ba4c` |
| `Blender281rgb32.exr` | 93,777,695 | 3 FLOAT | `42c3866a3eae8c11f4ce7065a6d9f1c3a0d304d49be2c353b0d7e3bd670cae1b` |
| `Blender281layered16.exr` | 172,203,728 | 21 HALF | `004fbf54e432b465956391e235fb65911fcbf2bed4188c12b81314573d0c9110` |
| `Blender281layered32.exr` | 502,238,676 | 21 FLOAT | `3adaadca0fc06b97c092b1fff3d041c819f6f57f641e02d9f077955284fd8a55` |
| `Blender35.exr` | 159,651,680 | 15 HALF + 3 FLOAT | `5e9f5423d113e00370bcec89740819102f33996a09cab79b2b68b3c6575a09d5` |
| `Blender40.exr` | 141,932,295 | 8 HALF + 7 FLOAT | `1fb741407a8fc8075cd517c62d92b99163f64710974c74cd5a532a544c7c611c` |
| `Blender41.exr` | 422,401,171 | 27 HALF + 10 FLOAT | `5819046938145a559b63e3fb1ec929d1b331d424bb4d39b9f1158f79f29b525c` |
| `Blender43.exr` | 34,691,621 | 3 HALF | `62132a72ff79c2d0a9c918b6c9c8e7a89a14f2ca65b4fca9ddcabf29d3fd6609` |

The eight compressed sources total 1,554,393,182 bytes. All are OpenEXR v2,
single-part, non-deep, nontiled ZIP scanline images with full-resolution
3840x2160 channels.

## Numeric material

Pinned TinyEXR v1.0.12 leaves each requested type equal to its source type.
Every source channel is decoded independently and written in canonical
little-endian row-major order without scaling, normalization, clipping, color
conversion, or HALF/FLOAT promotion.

| Series | Samples | Values | Bytes | Benchmark eligible |
|---|---:|---:|---:|---:|
| native binary16 channel planes | 77 | 638,668,800 | 1,277,337,600 | 68 |
| native binary32 channel planes | 44 | 364,953,600 | 1,459,814,400 | 43 |
| **Total** | **121** | **1,003,622,400** | **2,737,152,000** | **111** |

All decoded values are finite. Ten alpha planes are exactly constant at one:
nine HALF and one FLOAT. They remain registered to represent the complete EXR
contents, but index rows mark them `benchmark_eligible = false` so they do not
artificially improve aggregate compression results.

## Verification and evaluation discipline

Build and independent verification passed. Verification recomputes every
source/tool hash, recompiles TinyEXR integration code, freshly decodes all 121
planes, and compares every output SHA-256, geometry, type, byte count,
classification, and little-endian marker.

These files are an evaluation suite, not automatically an unseen holdout. A
model or codec must be frozen before measurement; repeated tuning against this
suite converts it into development data and invalidates an OOD claim.
