# Qwen2.5-7B-Instruct GSM8K last-layer hidden-state bfloat16 development

## Outcome

Accepted `hf_qwenmath_qwen25_7b_lastlayer_hidden_bf16`. Each sample is one sampled GSM8K solution trace of `Qwen/Qwen2.5-7B-Instruct`: the `bytoken_lastlayer` tensor `[T_gen, 3584]`. It holds the final-layer hidden state (`hidden_states[-1]`, index 28 of 29, which comes after the final RMSNorm in HF Qwen2) for every generated token, stored by the publisher as native bfloat16 and copied verbatim.

This is the corpus's third LLM hidden-state family at 16 bits. It is new content in a known modality, not a new modality. The two existing families are:

- `hf_uq_gemma4_31b_mmlupro_residual_f16`: Gemma-4-31B, raw mid-depth residual, prompt plus generated tokens;
- `hf_tdig_evo2_7b_hg38_final_norm_hidden_f16`: Evo 2 7B DNA LM, final-norm output.

Both are stored as IEEE fp16 of bf16 content, with the low 3 mantissa bits zero. This recipe is the first LLM activation family in native bf16. 87.2% of its values have live low mantissa bits, and its high byte carries sign plus 7 exponent bits, so the byte-lane structure differs. It is also a text transformer's final post-norm state over generated tokens only. zlsim says OK: nearest feature distance 0.0619 (Gemma), but that compressor's loss is 0.0, so the family is compression-equivalent to the LLM-tensor cluster and novel only on features.

## Source and rights

- Cache: Hugging Face dataset `lzhang472/qwen-math-hidden-states`, revision `1b8d08c6c6bca2c3ebad597f3ea0802c9d420910` (lastModified 2026-07-04). Ungated and public; card frontmatter `license: apache-2.0` (card sha256 `dffacb6b…6446061`, 1,377 B); API tag `license:apache-2.0`.
- Trace manifest: `manifest.jsonl`, 10,649,660 B, sha256 `17b44c8f…308631`, 6,240 rows. It has 800 qwen25_inst GSM8K rows: 100 problems × 8 samples, all `stop`, one config hash `429b665ea67a`.
- Model: `Qwen/Qwen2.5-7B-Instruct` at `a09a35458c702b33eeacc393d103063234e8bc28`, `license: apache-2.0`. Only the card is fetched.
- Prompts: `openai/gsm8k` at `740312add88f781978c0658806c59bc2815b9866`, `license: mit`. No text is emitted.
- download.sh re-checks all three license lines, pins every file by size and SHA-256, uses curl only, and passes no credentials. The material contains no personal data.

## Shape and conversion

- Natural record: one sampled solution trace, i.e. one safetensors file `mdl-qwen25_inst__ds-gsm8k__pid-<problem>__k<k>.safetensors`.
- Each file is parsed with a pure-stdlib reader. It must hold exactly three tensors (`bytoken_lastlayer`, `bylayer_mean_gen`, `bytoken_proj`) with contiguous offsets ending at the file size, and metadata `T_gen` and `trace_id` equal to the manifest row. `bytoken_lastlayer` must be BF16 `[T_gen, 3584]` with byte length T×3584×2.
- The tensor bytes (little-endian, row-major `[token, hidden_dim]`) are written unchanged. There is no cast, rescale or inference.
- Excluded: `bytoken_proj`, a random 512-d projection, and `bylayer_mean_gen`, which is read only to check that the emitted tensor is the final layer. Also excluded: Qwen3 models, MATH-500 (LaTeX-heavy, partly truncated at 1024 tokens) and AIME.
- Selection: samples k0, k1 and k2 of all 100 cached GSM8K problems, pinned in `scripts/selected_files.tsv`. All 800 traces would be about 1.7 GB of primary data, over the cap. Taking all problems first favours breadth.

## Accepted output

- Primary samples: 300 (100 problems × 3 sampled traces), 0 dropped
- Token rows: 89,700
- Primary values: 321,484,800
- Primary bytes: 642,969,600
- Download: 807,951,696 bytes (cards, manifest.jsonl, 300 safetensors files)
- Minimum sample: 148 tokens, 530,432 values (1,060,864 B)
- Median sample: 279.5 tokens, about 1,001,728 values (about 2.0 MB)
- Maximum sample: 920 tokens, 3,297,280 values (6,594,560 B)
- Value range: [-248.0, 292.0], no inf or NaN
- Per-sample std: 4.02–5.07
- Distinct codes per sample: 3,783–4,465
- Order-0 entropy: about 10.6 bits per value
- Zeros: 290,161 (0.09%)
- Final-layer mean cosine: at least 0.999997 in every sample
- Labels: 267 correct, 33 incorrect
- zlsim: verdict OK, own ratio 1.50, mode share 0.0019. Nearest families:
  - Gemma residual: 0.0619 (loss 0.0)
  - SmolLM2 weights: 0.0655 (loss 0.0013)
  - Evo 2 final norm: 0.0793 (loss 0.063)

## Judge checks

- `gate.py`: PASS with no warnings (median 1,001,728 values, width 16).
- `verify.sh` run by the judge: exit 0 in 37 s, "verified samples=300 dropped=0 primary_values=321484800 primary_bytes=642969600". build.sh and qwenmath_hidden.py read only local files.
- Bytes: I decoded 6 random samples with stdlib `array`/`struct`.
  - File size is exactly T×3584×2.
  - 87.2% of values have nonzero low-3 mantissa bits, which shows true bf16, not a widened or re-cast encoding.
  - High-byte mass sits at 0x3E–0x40 and 0xBE–0xC0.
  - Row L2 norms are 184–300, nearly constant, consistent with post-RMSNorm.
  - |x| p50 is about 1.8, p99 about 12, p99.99 127–150.
  - Massive channels 1069 (+64 to +87) and 46 (−43 to −55) recur in every sample.
  - Lag-1 token cosine median is 0.37–0.55.
- Layer identity: I recomputed this independently from two source files. The per-dimension token mean has cosine 1.0 against `bylayer_mean_gen` row 28 and 0.18–0.21 against row 27. The layer-mean norm falls from about 307 at L27 to about 120 at L28, which confirms the final post-norm state.
- Duplication:
  - 3,473 of 89,700 rows (3.9%) are exact duplicates. All come from shared opening tokens of continuations sampled from the same prompt; the first row is identical in 169 of 300 same-problem pairs, and the mean exact shared prefix is 13.8 rows.
  - Counting near-duplicates (cosine ≥ 0.999), the upper bound is about 6.8%.
  - This is natural and modest. No sample is a concatenation.
- Rights:
  - I read the pinned cache card.
  - My Hub API probe at the pinned revision shows gated=False, private=False, license apache-2.0.
  - I checked the frontmatter of the model card (apache-2.0) and the GSM8K card (mit).
  - No credentials appear in any script.
- Novelty: `novelty.py --url` matches only this staging recipe. `--type llm_hidden_state` returns the two accepted fp16 families above, with 0 instrument or archive matches and no downstream activation families. The card's `new_modality` claim was stale; the honest label is `new_content_same_modality`.
- Volume: 300 samples across all 100 problems, 643 MB primary from an 808 MB download (1.26:1). The bound is forced by the 1 GB cap and favours breadth across problems.
