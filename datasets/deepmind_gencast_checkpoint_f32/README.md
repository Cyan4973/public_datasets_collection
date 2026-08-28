# DeepMind GenCast checkpoint float32 probe

This candidate targets native float32 parameter tensors from the official
GenCast 1-degree Mini checkpoint.  The intended samples are complete individual
parameter tensors, especially dense, attention, and graph-message-passing
matrices.  Tensor boundaries and shapes must be preserved; unrelated
parameters must never be concatenated or interleaved.

This is distinct from the accepted `hf_timm_resnet18_conv_f32` family, which
contains rank-4 image-convolution kernels.  GenCast may add rank-2 learned
matrices and other architecture-specific tensor shapes from a probabilistic
graph-based weather model.  It is also distinct from the blocked GenCast
forecast-data attempt: this candidate uses model weights from the explicitly
licensed `dm_graphcast` bucket, not WeatherBench2 predictions.

Run the bounded probe:

```sh
bash datasets/deepmind_gencast_checkpoint_f32/probe_npz.sh
```

The script:

- pins the official Google DeepMind repository revision and validates the
  commercial-use model-weight update plus CC BY 4.0 material license;
- validates the exact public GCS object metadata for
  `GenCast 1p0deg Mini <2019.npz`;
- downloads only the final 8 MiB needed to parse the ZIP/NPZ central directory;
- selects at most 64 of the largest stored `.npy` entries and fetches only an
  8 KiB range at each local-header offset; and
- reports native dtype, shape, tensor rank, and projected usable float32 volume.

No complete tensor or checkpoint is downloaded.  Results are written under
`.data/probes/deepmind_gencast_checkpoint_f32/`, with logs under
`.data/logs/deepmind_gencast_checkpoint_f32/`.

Proceed to full acquisition only if the archive exposes substantial native
little-endian float32 tensors with useful complete-sample sizes.  BF16/F16
weights must not be widened and would instead require a separately justified
16-bit family.

The bounded probe found 363 stored NPY members.  All 64 largest entries are
native little-endian float32 rank-2 matrices, totaling 174,063,616 payload
bytes.  They include transformer feed-forward matrices (`2048x512` and
`512x2048`), `512x512` attention projections, and graph-network MLP matrices.
This is sufficient evidence to acquire the exact 230,105,815-byte checkpoint:

```sh
bash datasets/deepmind_gencast_checkpoint_f32/download.sh
```

The downloader reuses the already-probed license documents, validates the
pinned GCS size and MD5, then verifies the complete 363-member stored-NPY ZIP
inventory and every member CRC.  It does not yet emit training samples.

The complete checkpoint confirms 160 selected C-order float32 matrices across
four separate families:

- 32 transformer feed-forward matrices;
- 64 transformer attention projection matrices;
- 21 grid/mesh graph-network MLP matrices; and
- 43 conditioning projection matrices.

Together they contain 57,342,976 values and 229,371,904 primary bytes.  The
build excludes biases, configuration/description scalars, two tiny Fourier
feature matrices, and the sole Fortran-order matrix rather than changing its
source storage order.

The checkpoint's embedded license string still names the former CC BY-NC-SA
4.0 terms.  The pinned official README explicitly states that the model-weight
license was updated on 2026-08-06 to permit commercial use and that the
previous license is replaced, including for weights previously sourced from
the repository.  The build validates both the stale embedded notice and the
explicit supersession statement.

Build and independently verify the samples with:

```sh
bash datasets/deepmind_gencast_checkpoint_f32/build.sh
bash datasets/deepmind_gencast_checkpoint_f32/verify.sh
```
