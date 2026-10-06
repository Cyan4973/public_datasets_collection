# MACE-MP foundation checkpoints: native float64 parameter tensors

Complete trained `torch.nn.Parameter` tensors from **all ten MIT-licensed
MACE-MP foundation interatomic-potential checkpoints** published as GitHub
release assets of [ACEsuit/mace-foundations](https://github.com/ACEsuit/mace-foundations).
MACE trains in float64 (`default_dtype=float64`), and the checkpoints store
every parameter as a little-endian `torch.DoubleStorage`. One sample is one
complete parameter tensor with at least 1,000 values, the same convention as
`hf_timm_resnet18_conv_f32` and `deepmind_gencast_checkpoint_f32`.

## Scope

The scope is every checkpoint linked from the MIT rows of the pinned README model
table (revision `16a9f178706ce053f3ca8531efbab00a305d0854`):

| tag | generation | release asset | bytes | selected tensors | values |
|---|---|---|---:|---:|---:|
| mace_mp_0a_small | MACE-MP-0a | mace_mp_0/2023-12-10-mace-128-L0_energy_epoch-249.model | 32,581,838 | 22 | 3,846,272 |
| mace_mp_0a_medium | MACE-MP-0a | mace_mp_0/2023-12-03-mace-128-L1_epoch-199.model | 44,422,970 | 25 | 4,687,232 |
| mace_mp_0a_large | MACE-MP-0a | mace_mp_0/2024-01-07-mace-128-L2_epoch-199.model | 63,509,066 | 28 | 5,723,648 |
| mace_mp_0b_small | MACE-MP-0b | mace_mp_0b/mace_agnesi_small.model | 67,603,120 | 22 | 8,220,800 |
| mace_mp_0b_medium | MACE-MP-0b | mace_mp_0b/mace_agnesi_medium.model | 79,447,096 | 25 | 9,061,760 |
| mace_mp_0b2_small | MACE-MP-0b2 | mace_mp_0b2/mace-small-density-agnesi-stress.model | 67,622,684 | 22 | 8,220,800 |
| mace_mp_0b2_medium | MACE-MP-0b2 | mace_mp_0b2/mace-medium-density-agnesi-stress.model | 79,462,798 | 25 | 9,061,760 |
| mace_mp_0b2_large | MACE-MP-0b2 | mace_mp_0b2/mace-large-density-agnesi-stress.model | 98,544,548 | 28 | 10,098,176 |
| mace_mp_0b3_medium | MACE-MP-0b3 | mace_mp_0b3/mace-mp-0b3-medium.model | 79,472,952 | 25 | 9,061,760 |
| mace_mpa_0_medium | MACE-MPA-0 | mace_mpa_0/mace-mpa-0-medium.model | 79,462,305 | 25 | 9,061,760 |

The total is 692,129,377 bytes downloaded, giving 247 samples with 77,043,968
float64 values (616,351,744 primary bytes).

The recipe does not download:
- `MACE_MPtrj_2022.9.model` and `2023-12-10-mace-128-L0_epoch-199.model`. Both
  are in the `mace_mp_0` release but are not linked from the README table.
- training data such as `training_data.zip`, `mp_traj_combined.xyz` and
  `descriptors.npy`.
- the ASL-licensed releases: OMAT, MATPES, OMOL, MH and POLAR.

## Series

| series | samples | values | bytes | geometry |
|---|---:|---:|---:|---|
| `mace_equivariant_linear_weight_f64` | 100 | 63,098,112 | 504,784,896 | rank-1 flattened e3nn path weights |
| `mace_radial_mlp_weight_f64` | 60 | 1,277,952 | 10,223,616 | rank-2 (64x64, 64x512/1280/2176) |
| `mace_symmetric_contraction_weight_f64` | 87 | 12,667,904 | 101,343,232 | rank-3 (89 elements x basis x 128 channels) |

- **Equivariant linear:** `node_embedding.linear`, `interactions.N.linear_up`,
  `interactions.N.linear`, `interactions.N.skip_tp`, `products.N.linear` and
  `readouts.1.linear_1` weights. `interactions.0.skip_tp.weight` is the largest
  tensor: 128x89x128 per irrep path, 1.46 M values in 0a and 5.83 M values in
  the 0b family. It is a trained Parameter (the species-dependent
  self-connection), not a buffer.
- **Radial MLP:** layer1–layer3 of each interaction's `conv_tp_weights` network.
- **Symmetric contraction:** `weights_max`, `weights.0` and `weights.1` per
  product block and output irrep.
- **Excluded parameters:** below 1,000 values are `conv_tp_weights.layer0`
  (512–640), `density_fn.layer0` (8–10), `readouts.0.linear` (128) and
  `readouts.1.linear_2` (16).
- **Excluded buffers:** all buffers are excluded. They include U-matrix coupling
  coefficients, atomic energies, scale/shift, radial-basis constants and atomic
  numbers.

## Decode

Each `.model` file is a STORED PyTorch zip: `<prefix>/data.pkl`,
`<prefix>/data/<key>` raw storages, `version`, and in newer files `byteorder`
and `.data/serialization_id`. Members carry data descriptors, so sizes and
offsets come from the central directory. The member prefix differs per file;
for example, 0b3 uses `mace-medium-ema-99999_99/`.

`scripts/torch_zip_pickle.py` decodes `data.pkl` with a subclassed
`pickle.Unpickler`. torch, mace and e3nn are never imported:

- Only `collections.OrderedDict`, `builtins.set` and `_codecs.encode` resolve to
  real callables.
- `torch._utils._rebuild_tensor_v2` and `_rebuild_parameter` become recorders of
  storage key, offset, size and stride.
- `torch.{Double,Float,Long}Storage` become dtype markers for `persistent_load`.
- Every other `mace.*`, `e3nn.*` or `torch.*` global becomes an inert stub that
  only stores its arguments and state. Anything else raises.

The module tree is walked through the pickled `_modules`, `_parameters` and
`_buffers` dicts. The loader fails in any of these cases:
- some rebuilt tensor is unnamed
- a parameter is named twice
- two tensors share a storage
- a selected parameter is not float64, is non-contiguous, or overruns its storage

The emitted bytes are exactly `storage[offset*8 : (offset+numel)*8]`.

`scripts/selftest_synthetic.py` runs first in `build.sh`. It builds a synthetic
protocol-2 checkpoint without torch, using the same globals, a ParameterList, an
offset view and data-descriptor members, and checks:
- names, offsets and strides
- both member readers
- statistics, including NaN rejection
- the near-duplicate screen
- rejection of an `os.system` global

## Native float64 evidence

The realized build has 0 of 77,043,968 values that round-trip through float32.
It also has 1,400,688 float64 subnormals: 8.3% of symmetric-contraction values
and 0.56% of equivariant-linear values.

Many weights were driven by weight decay to magnitudes between 1e-20 and 1e-320,
which float32 cannot represent. Of the 247 tensors, 18 are more than 50% values
with |x| < 1e-30, for example 0a `products.1` `weights_max` at about 96%. Those
tensors are still fully distinct values (262,016 distinct of 262,016), with
exponents mostly between 1e-200 and 1e-260. They are kept as genuine stored
parameters, not dropped.

The build records per-sample `f32_exact_count`, `subnormal_count` and
`zero_count`. There are no exact zeros in the output.

## Near-duplicate check

Later generations could in principle be fine-tunes of earlier ones. Two checks
rule this out:

- **Sampled screen:** the build compares every same-named, same-shape pair (911
  pairs) at up to 8,192 evenly spaced positions. A position matches when values
  are equal or within 1e-6 relative. The largest match fraction is 1.56%
  (0a small vs 0a medium `skip_tp`), far from the 50% exclusion threshold. No
  tensor is excluded.
- **Full exact-equality scan:** 208,965 values (0.27% of the output) equal the
  same-position value of an earlier checkpoint's same-named tensor. All of them
  are in the equivariant-linear series. Using the `atomic_numbers` buffer, they
  map to:
  - the neon (Z=10, z_table index 9) `node_embedding` row (128 values);
  - the neon `skip_tp` block (1/89 of the tensor);
  - in the 0b family, part of the argon (Z=18) `skip_tp` block.

  Neither element has gradient in MPtrj, so these blocks keep the same-seed
  initialization. Nine tensors carry such blocks, at most 1.54% of a tensor
  (0b medium `skip_tp`). The count is pinned, and the build and verify fail if
  it changes or if any tensor is 50% or more an exact copy.

Probe-time head comparison agrees: across the 45 checkpoint pairs, median
correlation is about 0. The 0.5–0.87 correlations in some first-layer tensors of
same-seed runs come with almost no close values, and MPA-0 stays at or below
0.13 against all other checkpoints.

## Pins

- **License documents:** README.md and LICENSE at the pinned revision, by size
  and sha256. `validate-docs` requires `MIT` in the license cell of the
  MACE-MP-0a/0b/0b2/0b3/MPA-0 rows, and requires each row to link the downloaded
  asset or its release tag.
- **Checkpoints:** size, member count and prefix, central-directory offset, and
  the sha256 of the bytes from the central directory to EOF. That hash pins every
  member name, size, offset and CRC32. Also pinned are the `data.pkl` size and
  sha256, and a CRC check of every member.
- **Full-file sha256:** pinned for all ten checkpoints. GitHub publishes no
  digest for these pre-2025 assets. For 0b2 S/M/L, 0b3 and MPA-0, the values are
  the Hugging Face LFS oids of the byte-identical mirrors
  `mace-foundations/mace-mp-0` and `mace-foundations/mace-mpa-0`; the downloads
  matched them. The 0a and 0b values were recorded from the first verified
  download, which passed the size, central-directory, `data.pkl` and member-CRC
  checks.

## Running

```sh
bash staging/mace_mp_foundation_model_weights_f64/download.sh   # ~692 MB, resumable
bash staging/mace_mp_foundation_model_weights_f64/build.sh
bash staging/mace_mp_foundation_model_weights_f64/verify.sh
```

`verify.sh` re-slices every payload by raw local-header offset (not
`zipfile`). It recomputes all statistics from both source and emitted bytes,
then checks the index, `ingest_stats.json`, the exact sample-file inventory and
the manifest totals.

## License

MIT (repository LICENSE, Copyright (c) 2024 MACE-MP). The README table marks
each of the five included generations as MIT. Cite Batatia et al., *A
foundation model for atomistic materials chemistry*, arXiv:2401.00096.
