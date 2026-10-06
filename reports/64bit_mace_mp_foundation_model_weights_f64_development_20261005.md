# MACE-MP foundation checkpoint float64 parameter-tensor development

## Outcome

Accepted `mace_mp_foundation_model_weights_f64`. It collects complete trained `torch.nn.Parameter` tensors from all ten MIT-licensed MACE-MP foundation interatomic-potential checkpoints: MACE-MP-0a small/medium/large, 0b small/medium, 0b2 small/medium/large, 0b3 medium and MPA-0 medium.

MACE trains in float64, and the checkpoints store every parameter as a little-endian `torch.DoubleStorage`. This is the first 64-bit neural-network-weight family in the local corpus. It fills the downstream `nn_weight_f64` slot (`downstream_mirror_fill`). That downstream family is 72k DINO/GPT-2 values, all of them float32-exact, so it is widened f32. This recipe holds weights that were genuinely trained in float64.

## Source and rights

- Source: GitHub release assets of `ACEsuit/mace-foundations`, under release tags `mace_mp_0`, `mace_mp_0b`, `mace_mp_0b2`, `mace_mp_0b3` and `mace_mpa_0`.
- Downloaded: 692,129,377 bytes of checkpoints plus the pinned README (9,392 B) and LICENSE (1,064 B), both at revision `16a9f178706ce053f3ca8531efbab00a305d0854`.
- Pins:
  - full-file sha256 for all ten checkpoints;
  - the central-directory tail sha256, which covers every member CRC, size and offset;
  - `data.pkl` size and sha256;
  - parameter and buffer inventories.
- Where the sha256 values come from:
  - 0b2, 0b3 and MPA-0: they match the Hugging Face LFS oids of byte-identical mirrors.
  - 0a and 0b: recorded from the first verified download.
- License: MIT.
  - The pinned README model table ends the MACE-MP-0a, 0b, 0b2, 0b3 and MPA-0 rows with `| MIT |`.
  - The repository LICENSE is the MIT License.
  - The HF mirrors `mace-foundations/mace-mp-0` and `mace-foundations/mace-mpa-0` are tagged `license:mit`.
- Not downloaded:
  - the ASL-licensed OMAT, MATPES, OMOL, MH and POLAR releases;
  - the files not linked from the table: `MACE_MPtrj_2022.9.model` and `L0_epoch-199`;
  - all training data and descriptors.

## Shape and conversion

Each `.model` file is a STORED PyTorch zip. A pure-stdlib inert unpickler decodes `data.pkl`:

- Only `OrderedDict`, `set` and `_codecs.encode` are real callables.
- `_rebuild_tensor_v2` and `_rebuild_parameter` are replaced by recorders.
- Other `mace.*`, `e3nn.*` and `torch.*` globals become inert stubs.
- torch is never imported.

The module tree is walked through the pickled `_modules`, `_parameters` and `_buffers` dicts. The build fails if any tensor is unnamed, any storage is shared, or any selected parameter is not float64.

One natural record is one complete float64 Parameter with at least 1,000 values. It is emitted verbatim as storage elements `[offset, offset+numel)`; all offsets are 0 and all tensors are C-contiguous. All buffers are excluded: U matrices, atomic energies, scale/shift, radial constants and atomic numbers. Parameters below 1,000 values are also excluded: radial `layer0` (512–640), `density_fn` (8–10), `readouts.0.linear` (128) and `readouts.1.linear_2` (16).

The output is three series split by tensor role and geometry:

- `mace_equivariant_linear_weight_f64`: rank-1 e3nn path weights from `node_embedding.linear`, `linear_up`, `linear`, `skip_tp`, `products.linear` and `readouts.1.linear_1`.
- `mace_radial_mlp_weight_f64`: rank-2 `conv_tp_weights` layer1–3 matrices.
- `mace_symmetric_contraction_weight_f64`: rank-3 element × coupling-basis × channel `weights_max` / `weights.K`.

## Accepted output

| series | samples | values | bytes | min / median / max values |
|---|---:|---:|---:|---|
| mace_equivariant_linear_weight_f64 | 100 | 63,098,112 | 504,784,896 | 2,048 / 32,768 / 5,832,704 |
| mace_radial_mlp_weight_f64 | 60 | 1,277,952 | 10,223,616 | 4,096 / 4,096 / 139,264 |
| mace_symmetric_contraction_weight_f64 | 87 | 12,667,904 | 101,343,232 | 11,392 / 45,568 / 740,480 |
| **total** | **247** | **77,043,968** | **616,351,744** | median 32,768 |

- float32-exact values: 0
- float64 subnormals: 1,400,688 (8.3% of symmetric-contraction values, 0.56% of equivariant-linear values)
- exact zeros: 0
- weight-decayed values with |x| < 1e-30: 4.0% overall. They sit in last-layer blocks that receive no gradient, are all distinct, and are kept as stored parameters.
- exact same-position equality with an earlier checkpoint: 208,965 values (0.27%). These are untrained neon (Z=10) and argon (Z=18) blocks left at same-seed initialization; the largest share in any tensor is 1.54%. The figure is pinned.
- near-duplicate exclusions: none. The highest sampled match fraction is 1.56%, against an exclusion threshold of 50%.

## Judge checks

- `gate.py`: PASS, no warnings. `check_repo_hygiene.py`: passed.
- I ran `verify.sh` myself: exit 0, 247 samples, `f32_exact=0`, 911 near-duplicate pairs compared.
- Independent decode with my own minimal stdlib unpickler:
  - 0a parameter totals are 3,847,696 / 4,688,656 / 5,725,072. They match the `mace_mp_0` GitHub release notes exactly; each equals selected values + 1,424 excluded sub-1000 parameters.
  - In all ten checkpoints, the selected storage keys equal the set of Parameters with at least 1,000 values, and none of them is a buffer.
  - All 247 samples are byte-identical to their zip-member storage slices.
- Bytes:
  - mantissas have full entropy (low-29-bit-zero fraction 0.0, all 256 low-byte values present);
  - per-tensor sd is 0.11–3.64 (linear), 1.1–4.8 (radial) and 0.03–0.68 (symmetric contraction);
  - skip_tp kurtosis is about 3.9, while symmetric-contraction tensors are heavy-tailed.
- Redundancy:
  - median same-name pair r is 0.004;
  - the highest r (0.86) is in small first-layer tensors of same-seed runs, with about 0% top-24-bit agreement;
  - the dominant 0b-family `skip_tp` tensors have r ≤ 0.20 and ≤ 2% top-24-bit agreement.
- Rights: I read the pinned README rows and the LICENSE text. The GitHub API reports the repo license as MIT, and the release asset listings confirm every downloaded file sits under an MIT-row tag. The HF API shows `license:mit` on both mirrors.
- Novelty: `novelty.py` found no MACE, e3nn or interatomic matches anywhere. I confirmed the downstream `nn_weight_f64` is 100% float32-exact (widened).
- Scripts: no credentials, no network code in the build or verify path, and `build.sh` reads only local `.data` files.
