# uq-hiddenstates Gemma-4-31B-it layer-45 residual-stream float16 development

## Outcome

Accepted `hf_uq_gemma4_31b_mmlupro_residual_f16`. Each sample holds the raw, unnormalized residual-stream hidden states of `google/gemma-4-31B-it` at hidden-state index 45 of 60, which is the output of decoder block 44 (relative depth 0.75). One 5376-wide float16 vector is stored per token position of one complete MMLU-Pro reasoning trace (prompt, chain of thought and answer).

This is the corpus's first accepted LLM activation / hidden-state family at any width. It is new as a quantity, not as a modality: the corpus already has learned neural-network representations (`hf_vbvr_wan22_vae_latents_bf16`, `google_alphaearth_satellite_embeddings_i8`) and NN weights (`hf_smolllm2_135m_safetensors_f16` and others). Residual-stream activations differ from those in their byte statistics. A few "massive activation" channels sit around 100–270 in every row, while the median |x| is about 0.57. Rows are strongly correlated along the token axis (lag-1 cosine median 0.93).

## Source and rights

- Cache: Hugging Face dataset `loose-bits/uq-hiddenstates`, revision `853e3392729d5ecc5663e4a635898085acc92109` (lastModified 2026-09-21). It is ungated, and the card frontmatter declares `license: apache-2.0`.
- Index: `gemma_mmlupro_L45.idx.json`, 138,017 bytes, SHA-256 `76307021af08a649f0cb578f11887528e156780d2c5463a218bf5048623eba55`. It lists 1000 items and 3,367,369 tokens across two shards.
- Shards: `gemma_mmlupro_L45.part00.npy` (21,459,572,864 B, LFS oid `4c186df9…bfd81338bda`) and `part01.npy` (14,746,378,880 B, oid `cff24898…1390f580b560`). Both are checked through the resolve endpoint's `x-linked-size` and `x-linked-etag` headers.
- Model: `google/gemma-4-31B-it` at `842da3794eaa0b77d5f08bae87a17459d91ff475` declares `license: apache-2.0`. Its `license_link` page (https://ai.google.dev/gemma/docs/gemma_4_license) is titled "Apache License 2.0 | Gemma" and contains the Apache 2.0 text with no output restrictions.
- Prompts: `TIGER-Lab/MMLU-Pro` at `b189ec765aa7ed75c8acfea42df31fdae71f97be` declares `license: mit`.
- download.sh re-checks all three license lines. No text, token ids or logits are fetched, and the material contains no personal data.

## Shape and conversion

- Natural record: one reasoning trace, the contiguous row block `[off, off+n)` of the shard named in the index. The index guarantees, and the scripts check, that items tile each shard exactly and that no trace spans two shards.
- Byte ranges: the shards are NPY v1 files (`'<f2'`, C order, shape `(rows, 5376)`, 128-byte header parsed from a 1024-byte range fetch). Each trace's bytes are therefore `128 + off*10752 .. 128 + (off+n)*10752 - 1`. They are fetched by HTTP Range GET, which must return 206 with the exact length, and written verbatim. There is no cast, rescale or inference.
- Representation: the publisher stored bf16 model states as fp16. The cast is exact in this magnitude range, so the low 3 mantissa bits are zero except at fp16-subnormal magnitudes. That leaves about 13 significant bits per 16-bit word, with both bytes varying. This is the published artifact, and each sample's index row records it as `low3_mantissa_nonzero_fraction`.
- Selection: every 37th of the 1000 index items, in index order (positions 0, 37, …, 999). The index is sorted by item id as strings, so the stride is independent of trace length and label. The selection is pinned in `scripts/selected_items.tsv` and re-derived by every script.
- Scope: only `gemma_mmlupro_L45` is used. Other datasets, models and the `*_k64` projections are excluded.

## Accepted output

- Primary samples: 28 (15 from part00, 13 from part01)
- Token rows: 71,398 (2.1% of the 3,367,369 published rows)
- Primary values: 383,835,648
- Primary bytes: 767,671,296
- Download: 767,862,139 bytes (cards, index, two NPY headers and 28 trace ranges)
- Minimum sample: item 11229, 920 tokens, 4,945,920 values (9,891,840 B)
- Median sample: 10,300,416 values (1,916 tokens)
- Maximum sample: item 9170, 9,371 tokens, 50,378,496 values (100,756,992 B)
- Value range: [-97.0, 272.0], with no inf or NaN
- Per sample: 4,940–5,385 distinct codes, order-0 entropy 10.499–10.532 bits, zero fraction about 0.06%, minimum per-row distinct codes 1,416
- Low-3 mantissa bits nonzero: 0.025–0.031% per sample, all subnormal
- Labels: 27 correct, 1 incorrect (base rate 109/1000 incorrect)
- zlsim: verdict OK, own-compressor ratio 1.51, nearest family downstream `smollm_embed` at distance 0.0844 (loss 0.0438). The candidate's mode share is 0.0027.

## Judge checks

- `gate.py`: PASS with no warnings (median 10,300,416 values, width 16).
- `verify.sh` run by the judge: exit 0, "verify ok: 28 samples, 767671296 bytes", 52 s.
- build.sh and uq_hidden.py read only local files and make no network calls. download.sh uses curl only, pinned to the revision, with no credentials.
- Alignment: every sample starts with the same byte-identical BOS row, and no trace contains a second BOS row. Offsets are correct and no sample is a concatenation.
- Cross-trace duplicate rows: 157 of 71,398 (0.22%), all at token positions 1–52. They are shared chat-template prefix rows and are natural.
- Distribution (items 100, 12004, 9170): |x| p50 about 0.57–0.62, p99 about 3.0, p99.99 about 5.4–6.0. Channel 2041 has a median of 140–159. Channels 3970, 1376 and 1451 reach 50–100. Row L2 norm is about 196 at BOS and 115–230 elsewhere.
- Low-bit structure: every value with nonzero low-3 mantissa bits is fp16-subnormal, which confirms the bf16-in-fp16 reading. I judge this to be the publisher's representation, not recipe widening.
- Rights:
  - I opened the cache card and the Gemma 4 license page.
  - The HF API at the pinned revision reports gated=False and license apache-2.0.
  - I checked the MMLU-Pro card frontmatter (mit).
- Novelty: `novelty.py` `--type`, `--instrument` and `--archive` return 0 matches. The vocabulary has no activation type, and downstream 16-bit families are weights and tokens only. Sibling hidden-state candidates (`hf_qwenmath_qwen25_7b_lastlayer_hidden_bf16`, `hf_tdig_evo2_7b_hg38_final_norm_hidden_f16`) are not accepted. They should be compared against this family when they reach zlsim.
- Volume: 28 unbiased samples is close to the most the 1 GB cap allows at about 36 MB per trace. Download and kept bytes are about 1:1.
- Minor: `staging/.../scripts/__pycache__/` exists and should not be carried into `datasets/` on promotion.
