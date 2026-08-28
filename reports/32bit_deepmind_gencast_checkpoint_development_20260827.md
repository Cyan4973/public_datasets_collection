# DeepMind GenCast checkpoint float32 development

## Outcome

Accepted `deepmind_gencast_checkpoint_f32` as a new AI-model num32 family.  It
contains 160 complete native-float32 rank-2 parameter matrices from Google
DeepMind's GenCast 1-degree Mini probabilistic weather model:

| Family | Samples | Values | Bytes |
|---|---:|---:|---:|
| Transformer feed-forward weights | 32 | 33,554,432 | 134,217,728 |
| Transformer attention weights | 64 | 16,777,216 | 67,108,864 |
| Grid/mesh graph-network weights | 21 | 6,306,816 | 25,227,264 |
| Conditioning projection weights | 43 | 704,512 | 2,818,048 |
| **Total** | **160** | **57,342,976** | **229,371,904** |

This is structurally distinct from the accepted ResNet-18 float32 family,
which contains rank-4 image-convolution kernel banks.  GenCast contributes
dense transformer projections, feed-forward expansion/contraction matrices,
weather-grid/icosahedral-mesh message-passing matrices, and diffusion/noise
conditioning projections.

## Source and bounded preflight

The selected source is the official public object:

```text
dm_graphcast/gencast/params/GenCast 1p0deg Mini <2019.npz
```

- GCS generation: `1733326322411726`
- source bytes: `230,105,815`
- MD5: `390a43c43cb6f49ea46d7ffc7104cc99`
- SHA-256:
  `a8dc94b616af89cfc01a5c6afbcc8411b594d919f23f3cd962f6f7755735195e`

Before full acquisition, the user downloaded only the final 8 MiB of the NPZ
and 64 bounded 8 KiB member-header ranges.  That established a simple archive
of 363 uncompressed NPY members and showed that all 64 largest entries were
native little-endian float32 rank-2 matrices.  The probed matrices alone
contained 174,063,616 float32 bytes.

The full downloader validates the pinned identity, all 363 ZIP members, their
aggregate 230,022,753 member bytes, stored compression method, NPY-only
inventory, and every member CRC.

## Selection and representation

Each retained parameter tensor remains one natural sample.  The recipe removes
only ZIP and NPY framing and copies the complete source `<f4` payload verbatim,
so every output is already little-endian IEEE-754 float32.

The recipe keeps:

- all 32 transformer `ffw_up` and `ffw_down` matrices, shaped `512x2048` or
  `2048x512`;
- all 64 transformer query/key/value/final attention matrices, shaped
  `512x512`;
- 21 C-order grid-to-mesh and mesh-to-grid graph-network MLP matrices, ranging
  from 2,048 through 786,432 values; and
- all 43 conditioning matrices, each shaped `16x1024`.

It excludes 115 one-dimensional biases, 83 configuration/description scalars,
two tiny Fourier-feature matrices, and one `512x84` Fortran-order decoder
matrix.  The latter is excluded rather than reordered, keeping every accepted
sample byte-exact relative to its typed source payload.

All 160 outputs are finite, nonconstant, mutually byte-distinct, and use unique
paths.  Sample sizes range from 8,192 to 4,194,304 bytes.

## License resolution

The `dm_graphcast` bucket contains the complete CC BY 4.0 legal text.  The
pinned official repository README at revision
`9c034db1ff412d5db6cbe6bb0c5c9afc5a267719` additionally states:

- the model-weight license was updated on August 6, 2026;
- the new license permits commercial use;
- the previous license is replaced by the new README terms; and
- the update also applies to weights previously sourced from the repository.

The checkpoint's embedded `license.npy` still contains the former CC
BY-NC-SA 4.0 notice.  Unlike the unresolved AlphaMissense conflict, this release
contains an explicit, dated supersession statement specifically covering model
weights.  The recipe pins and validates both the stale embedded notice and the
new official replacement terms so future wording drift fails closed.

## Verification

Build and verification independently reparse the pinned checkpoint, validate
all NPY headers and payload lengths, reconstruct the exact selection, and
compare the index, statistics, output inventory, and every emitted byte against
the source member payload.  Both completed successfully.
