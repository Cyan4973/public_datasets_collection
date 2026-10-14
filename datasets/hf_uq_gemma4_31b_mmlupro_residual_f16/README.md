# uq-hiddenstates: Gemma-4-31B-it Layer-45 Residual Stream over MMLU-Pro Traces (float16)

Raw, unnormalized residual-stream hidden states of `google/gemma-4-31B-it`, recorded by
the Apache-2.0 Hugging Face cache `loose-bits/uq-hiddenstates` at hidden-state index 45
(output of decoder block 44 of 60, relative depth 0.75). There is one 5376-wide float16
vector per token position. Each sample is one complete MMLU-Pro reasoning trace (prompt,
generated chain of thought and answer) as an `[n_tokens, 5376]` row-major float16
matrix, copied verbatim from the published NPY shard.

## Why this material

Mid-depth residual-stream activations of a large LLM are a distinct numeric regime. A
handful of hidden channels carry "massive activations" (magnitudes around 100 in every row
we probed), while the median magnitude is about 0.5 to 1.5. Consecutive rows are
correlated along the token axis. The local corpus has no accepted activation or
hidden-state family. Its 16-bit ML families are model weights (SmolLM2 safetensors and
GGUF) and Wan2.2 VAE latents (`hf_vbvr_wan22_vae_latents_bf16`). Two sibling hidden-state
candidates are in the pipeline: `hf_qwenmath_qwen25_7b_lastlayer_hidden_bf16` (staging,
Qwen2.5-7B last layer, bfloat16) and `hf_tdig_evo2_7b_hg38_final_norm_hidden_f16`
(queued, Evo 2 final-norm states of DNA). This recipe differs from both in model, depth
and representation: raw states rather than final-norm or last-layer states, and fp16
holding bf16 content rather than bf16. Whether the bytes differ enough is for
`zlsim.py` to decide, not something this README claims.

## Source representation (read before judging width)

The model computes in bfloat16, and the publisher stored the states as float16 ("fp16
`[rows, hidden]` ... raw states, not normalized" on the card). The bf16-to-fp16 cast is
exact in this magnitude range, so the **low 3 mantissa bits are almost always zero**. In
probes, 1 to 4 of 5,376 values per row had them set, and only at fp16-subnormal
magnitudes. The low byte still varies freely. The content is therefore about 13
significant bits MSB-aligned in each 16-bit word. This is the publisher's native artifact,
like 12-bit sensor data stored in 16-bit words. The recipe performs no cast. Each sample's
`low3_mantissa_nonzero_fraction` is recorded in the index.

The first few rows of every trace are identical across traces, because every prompt
starts with the same chat-template prefix. This is part of the natural record and is
left in place.

## Provenance and license

- Cache `loose-bits/uq-hiddenstates`, revision `853e3392729d5ecc5663e4a635898085acc92109`,
  ungated: card frontmatter `license: apache-2.0`.
- Model `google/gemma-4-31B-it`, revision `842da3794eaa0b77d5f08bae87a17459d91ff475`,
  ungated: `license: apache-2.0`, `license_link:
  https://ai.google.dev/gemma/docs/gemma_4_license`. That page is titled "Apache License
  2.0 | Gemma".
- Prompts `TIGER-Lab/MMLU-Pro`, revision `b189ec765aa7ed75c8acfea42df31fdae71f97be`:
  `license: mit`.

`download.sh` fetches all three cards with pinned SHA-256 and re-checks each license
line. No text, token ids or logits are downloaded.

## Selection

The pinned `gemma_mmlupro_L45.idx.json` has 1000 items, which the card describes as
seeded stratified samples with one trace per item. Together they hold 3,367,369 tokens
in two NPY shards, 21.5 GB and 14.7 GB. The full family would be about 36 GB, so the
recipe takes **every 37th item in index order** (positions 0, 37, ..., 999): 28 traces,
15 from part00 and 13 from part01. That is 71,398 token rows and **767,671,296 bytes**.

The index is sorted by item id in string order (100, 104, 1081, 11229, ...), so the stride ignores trace length, and length predicts
the correctness label (the card says so). Realized trace lengths run from 920 to 9,371
tokens, with a median of about 1,900. 27 traces are correct and 1 is incorrect, against
a base rate of 109/1000 incorrect. Stride 37 was picked as the largest sample count that
stays under about 800 MB. Stride 33 or 34 would give 30 or 31 traces but about 1.0 GB.
`scripts/selected_items.tsv` pins the selection, and every script re-derives it from the
index and compares. Expect **28 samples**. That is in the acceptable range, not the
desirable 50+, because each natural record is large (11 to 100 MB) and the 1 GB cap
binds.

Only `gemma_mmlupro_L45` is used. The other source datasets (logiqa2, supergpqa, omnimath,
lcb, triviaqa), other models, and any `*_k64` projection files are excluded so the family
stays one model, one layer and one prompt distribution.

## Decode

The shards are NPY v1 files with `descr '<f2'`, C order and shape `(rows, 5376)`. The
header length is parsed from a 1024-byte range fetch and is 128 here. The index guarantees
that items tile each shard contiguously and that no trace spans two shards; the script
checks both. Trace `[off, off+n)` is therefore the byte range
`header_len + off*10752 .. header_len + (off+n)*10752 - 1`. `download.sh` fetches exactly
that range, requiring HTTP 206 and the exact length, and resumes partial files. The bytes
are already little-endian float16 and are emitted verbatim.

## Scripts

- `download.sh`: fetches the pinned cards and index (size + SHA-256) and checks the license
  lines. It checks each shard's LFS size and oid through the resolve endpoint's
  `x-linked-size` and `x-linked-etag` headers, then range-fetches and parses both NPY
  headers. It range-fetches the 28 traces and validates them (exact size, no inf/NaN),
  writing realized per-trace SHA-256 to `trace_sha256.tsv`.
- `build.sh`: re-validates the index, headers, selection and digests. Before writing each
  sample and its index row, it rejects degenerate traces: fewer than 4,096 distinct
  codes, a row with fewer than 256, duplicated adjacent rows, or a mode or zero fraction
  above 5%. Index rows carry the shape, item id, label, min/max and entropy.
- `verify.sh`: re-derives the byte ranges and compares every sample with its downloaded
  range. It recomputes min/max from decoded floats and distinct codes by set, which is a
  different path from build's histogram, and checks that no hidden channel is constant
  within a trace. It also checks manifest and stats totals.

## Status

Authored on 2026-10-14. Downloaded by the driver the same day: 767,862,139 bytes in
165 s, consisting of the cards, the index, two NPY headers and 28 trace ranges. Built
and verified the same day: 28 samples, 383,835,648 float16 values, 767,671,296 bytes,
no non-finite values. Each trace has 4,940 to 5,385 distinct codes, value ranges of
about [-97, 272] and an order-0 code entropy of about 10.5 bits. The minimum per-row
distinct-code count is above 1,400. `tools/autocollect/gate.py` passes.
`tools/autocollect/zlsim.py gate` on 2026-10-14 returned verdict OK (not redundant), with
an own-compressor ratio of 1.51. The nearest family is downstream `smollm_embed`, at
distance 0.084 against a threshold of 0.05 and loss 0.044 against 0.03. Next are
downstream SmolLM MLP/attention weights and the local
`hf_smolllm2_135m_safetensors_f16`, all at distance 0.088 to 0.092. The sibling
hidden-state candidates are not in the library yet, so they were not compared.
