# TDiG Evo 2 7B Final-Norm Hidden States over hg38 chr22 Windows, Float16

Native float16 hidden states of a DNA language model. Each sample holds the output of
the final RMSNorm of **Evo 2 7B** (`arcinstitute/evo2_7b_base`, 8K-context base model,
StripedHyena 2 architecture), taken at 600 token positions (every 10th nucleotide) of one
~6 kb window of the human reference genome hg38, chromosome 22. That is a
`(600, 4096)` matrix, 2,457,600 values, 4,915,200 bytes.

The tensors are published by the TDiG ("Think Deep in Genome") interpretability project
in the Hugging Face dataset `darejinn/TDiG-evo2-hidden-states` (pinned revision
`9f0d2a6a31ddd08ca4e3defab714dc7665634501`) as the HDF5 dataset `raw_h_norm` in
`chr22_tier3_raw.h5`.

## Why this material

These are learned activations of a genomic foundation model over real DNA. No accepted
recipe and no downstream family holds hidden states or activations (checked with
`novelty.py`); the accepted 16-bit ML families are weights and VAE latents. Two text-LLM
hidden-state drafts are in staging at the same time: `hf_uq_gemma4_31b_mmlupro_residual_f16`
(Gemma-4 residual stream, fp16) and `hf_qwenmath_qwen25_7b_lastlayer_hidden_bf16`
(Qwen2.5 last layer, bf16). This recipe differs from both in source model (a DNA
StripedHyena model, not a text transformer), in input (nucleotides, not text), and in
tensor (the final-norm output). Whether that difference shows up in the bytes is for the
zlsim gate to decide. Probe statistics, from sparse range reads:

- Each token row is dominated by a shared mean vector (rms about 0.5) plus one persistent
  outlier channel (index 3756, about +30). Variation between token positions is small but
  real: token rows 10 to 6,000 bases apart differ by 0.03 to 0.2 rms. Row 0 of every
  window is nearly identical across windows because the first token has no context.
- A 4,096-value row holds about 3,000 distinct fp16 codes.
- **bf16 provenance:** the model runs in bfloat16 and the publisher cast `h_norm` to
  float16 for storage (`raw_norm = h_norm[pos].cpu().numpy().astype(np.float16)` in the
  upstream `scripts/15_chr22_forward.py`). As a result the low 3 mantissa bits of the fp16
  codes are almost always zero (about 50 of 32,768 probed values had a nonzero low-3
  field). That is the publisher's storage format, not a local widening. The recipe emits
  the stored bytes verbatim, and the index records `low3_mantissa_nonzero` per sample.

## Provenance and license

- Dataset card (pinned): `license: mit`, and "## License MIT (matches GitHub repo)". The
  GitHub repository `YAICON-8th-Think-Deep-in-Genome/TDiG` is MIT-licensed.
- Model: the card names `arcinstitute/evo2_7b_base` revision `074097e9`. The model card at
  `074097e9dc788e8bfe045d6495b9f6153a7c6bfc` declares `license: apache-2.0` and is pinned
  by digest. No weights are downloaded.
- Input sequence: the UCSC hg38 reference assembly (GenBank-derived; "NCBI places no
  restrictions on the use or distribution of the GenBank data"). This is a reference
  mosaic with no personal genotype data. The repository's ClinVar variant files are not
  used.

## Selection

Scope is the complete chr22 tier-3 subset: all 100 windows of `chr22_tier3_raw.h5`. The
publisher picked these 100 from 12,978 non-N chr22 windows using
`scripts/05_select_subset.py`. It takes the top windows by coding-exon, intron, UTR,
splice and intergenic content, then fills with context-diverse windows. The resulting
`window_idx` values run from 0 to 12883 and include runs of adjacent windows. The
windows come from an N-filtered window table, and every window has `token_stride = 10`,
which means at least 6,000 tokens and no edge padding.

The following are excluded:

- `chr17_tier3_raw.h5`: same layout, another 491.5 MB. Including it would put the
  primary output at 983 MB, too close to the 1 GB cap. Downstream subsampling needs only
  about 100 MB per family.
- `raw_h_ell` (fp32, per-layer residual stream) and `raw_h_ell_rmsnormed` (per-layer):
  these are different quantities.
- The tier-2 scalars and the ClinVar variant files.

## Decode

`scripts/h5meta.py` is a minimal pure-stdlib HDF5 reader covering exactly what the file
uses: superblock v0, the root symbol table (v1 B-tree, SNOD, local heap) and v1 object
headers (dataspace, datatype, layout v3, filter-pipeline presence). It ran on the real
heads of both chr22 and chr17, and the shapes it reports match the dataset card. It finds:

| dataset | shape | dtype | layout |
|---|---|---|---|
| `raw_h_norm` | (100, 600, 4096) | IEEE binary16 LE | contiguous @ 471,870,248, 491,520,000 B, no filter |
| `window_idx` | (100,) | int64 LE | contiguous @ 2,936 |
| `token_stride` | (100,) | int32 LE | contiguous @ 963,390,248 |
| `done_mask` | (100,) | uint8 | contiguous @ 963,390,648 |
| `raw_h_ell`, `raw_h_ell_rmsnormed` | (100, 32, 600, 4096) | fp32 / fp16 | chunked (not used) |

Window `w` is bytes `[471,870,248 + w*4,915,200, +4,915,200)`. The address is re-derived
from the layout message at plan time and must also equal the pinned value.

## Scripts

- `download.sh`: fetches the two pinned cards (digest plus license line), checks the
  HDF5 object's size with a one-byte range GET, fetches the 64 KiB metadata head (pinned
  digest) and the 500-byte `token_stride`+`done_mask` span, then makes 100 range GETs of
  exactly 4,915,200 bytes (HTTP 206 and the exact length are required). Resume works per
  range: complete window files are kept on re-run. A semantic check then rejects
  non-finite, near-constant or duplicate windows. Total download is about 491.6 MB.
- `build.sh`: re-parses the head, re-checks the metadata and each window, writes each
  window verbatim to `samples/<id>/evo2_7b_final_norm_hidden_f16/chr22_window<idx>.f16`,
  and writes the index (with `window_idx`, `token_stride`, sha256, min/max from the
  stored fp16, rms, row spread, distinct codes) plus `filtered/<id>/ingest_stats.json`.
- `verify.sh`: re-derives the dtype and layout from the head, compares every sample
  byte-for-byte to its downloaded range, recomputes all statistics from the samples, and
  checks the index, ingest stats and manifest totals.
- `python3 scripts/tdig_evo2.py selftest`: tests float16 decoding, non-finite detection
  and the degeneracy checks on synthetic windows.

## Status

Authored on 2026-10-14. Downloaded, built and verified on 2026-10-14: the download was
491,611,762 bytes in 225 s, and the output is 100 samples, 245,760,000 values and
491,520,000 bytes. `gate.py` passes.

Realized statistics, computed from the stored fp16:

- Global min and max are -5.09 and 34.75. Per-window rms is 0.487 to 0.518.
- Token-row spread, the rms difference from the window's mean row, is 0.032 to 0.129.
- Each window holds 4,587 to 5,131 distinct codes.
- 137 values are exactly zero.
- 362,950 values (0.15%) have a nonzero low-3 mantissa field, which matches the
  bf16-origin estimate from the probe.
