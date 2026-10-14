# Qwen2.5-7B-Instruct GSM8K Last-Layer Hidden States BFloat16

Native bfloat16 LLM activations from a pinned, Apache-2.0 Hugging Face hidden-state cache
(`lzhang472/qwen-math-hidden-states`). Each sample is one sampled GSM8K solution trace of
Qwen2.5-7B-Instruct: the `bytoken_lastlayer` tensor `[T_gen, 3584]`, which holds the
final-layer hidden state of every generated token, copied verbatim.

## Why this material

This is the hidden state an LLM produces at inference time, not a weight tensor. The nearest
accepted family is `hf_uq_gemma4_31b_mmlupro_residual_f16`, also an LLM activation cache. It
differs in four ways: it is IEEE float16, not bfloat16, which gives a different exponent and
mantissa split and so different byte statistics; the model is Gemma-4-31B, not Qwen2.5-7B; it
stores the raw mid-depth (index 45 of 60) residual stream, not the final post-norm layer; and it
covers prompt and generated tokens of 28 MMLU-Pro traces. The other 16-bit ML content is SmolLM2
weights and the Wan2.2 VAE latents (bf16, but a video VAE, not an LLM). Probe of one trace
(`gsm8k-1001` k0, T = 282):

- 4,118 distinct BF16 codes, order-0 entropy 10.6 bits/value, range -168 to 243,
  std 4.7, 848 exact zeros out of 1.01 M values.
- Strongly structured along the hidden dimension: a few channels carry large means across
  all tokens (for example dim 1069 at about +87 and dim 46 at about -55), the
  "massive activation" pattern of RMSNorm LLMs. Token rows have L2 norms of 240 to 310.
- The per-dimension mean over tokens matches row 28 (the last) of the stored per-layer means
  `bylayer_mean_gen` (cosine 0.999999), and does not match row 27 (cosine 0.17). So
  the tensor is `hidden_states[-1]`, which for HF Qwen2 comes after the final RMSNorm.

## Provenance and license

- Cache: `lzhang472/qwen-math-hidden-states`, revision
  `1b8d08c6c6bca2c3ebad597f3ea0802c9d420910`, card `license: apache-2.0`, ungated.
- Model: `Qwen/Qwen2.5-7B-Instruct`, revision `a09a35458c702b33eeacc393d103063234e8bc28`,
  `license: apache-2.0`, ungated.
- Prompts: `openai/gsm8k`, revision `740312add88f781978c0658806c59bc2815b9866`, MIT.
- Sampling (from `manifest.jsonl`, identical for every selected trace): temperature 0.7,
  top_p 0.8, top_k 20, config hash `429b665ea67a`. All selected traces end with `stop`, and
  none is truncated (T_gen 148 to 920 is at most the cache's 1024-token limit).

## Selection

The cache holds 8 sampled traces for each of 100 GSM8K problems per model. Breadth across
problems comes first: the recipe takes samples k0, k1 and k2 of all 100 problems. That is
300 files, 797 MB to download and 643 MB of primary output (321,484,800 values; median
280 tokens = 1.0 M values per sample). Adding k3 would push the output to 856 MB. Excluded:

- Qwen3-4B-Instruct and Qwen3-4B-Thinking traces, which come from different models.
- MATH-500 traces: LaTeX-heavy outputs, 95 of the 800 cut at 1024 tokens. One coherent
  GSM8K regime is cleaner.
- AIME traces.
- The `bytoken_proj` random projection and `bylayer_mean_gen`. The latter is read only
  for the final-layer check.

`scripts/selected_files.tsv` pins the path, LFS size and SHA-256 of each file (resolved
with the Hub `paths-info` API from `manifest.jsonl` `x_path` at the pinned revision).

## Scripts

- `download.sh`: resumable curl fetch of the three pinned cards, `manifest.jsonl`, and the
  300 selected safetensors files, each checked by size and SHA-256. It then runs the full
  semantic validation (`qwenmath_hidden.py validate`).
- `build.sh`: parses each safetensors header (pure stdlib) and checks it against the
  manifest row: model, dataset, sampling config, T_gen and trace_id. It then checks BF16,
  `[T_gen, 3584]`, the byte length, finiteness, distribution sanity and the final-layer
  mean, writes the tensor bytes verbatim, and writes the index and `ingest_stats.json`.
- `verify.sh`: independently re-decodes every source and compares output bytes, index rows,
  stats, and the manifest `sample_count`/`total_size_bytes`.

Note: `numeric_kind = "float"`, `bit_width = 16` with `value_encoding = "bfloat16"`,
as in `hf_vbvr_wan22_vae_latents_bf16`. Generic tools that read float16 as IEEE half
will misinterpret the values; index `minimum`/`maximum` are computed from the BF16 codes.

## Status

Authored 2026-10-14. Downloaded (807,951,696 bytes, 660 s) and built on 2026-10-14:
300 samples, 0 dropped, 321,484,800 values, 642,969,600 bytes. Across samples: T_gen 148 to
920 (median 279.5), 3,783 or more distinct codes per sample, per-sample std 4.02 to 5.07,
global range -248 to 292, final-layer mean cosine of at least 0.999997. `verify.sh` and
`gate.py` pass.
