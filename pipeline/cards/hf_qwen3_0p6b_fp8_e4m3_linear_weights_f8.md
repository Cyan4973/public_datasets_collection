# Qwen3-0.6B-FP8 Official Checkpoint: Native FP8 E4M3 Block-Quantized (128x128) Transformer Linear-Layer Weight Tensors

- Candidate id: `hf_qwen3_0p6b_fp8_e4m3_linear_weights_f8`
- Width: float8
- Quantity: Trained LLM linear-projection weights (q/k/v/o attention, gate/up/down MLP) stored natively as 8-bit floats (OCP FP8 E4M3: 1 sign, 4 exponent, 3 mantissa bits) under fine-grained 128x128 block scaling; one value = one weight element's FP8 code
- Source: https://huggingface.co/Qwen/Qwen3-0.6B-FP8
- Resources: https://huggingface.co/Qwen/Qwen3-0.6B-FP8/resolve/main/model.safetensors, https://huggingface.co/Qwen/Qwen3-0.6B-FP8/resolve/main/config.json, https://huggingface.co/Qwen/Qwen3-0.6B-FP8/resolve/main/LICENSE
- License: Apache-2.0
- License evidence: https://huggingface.co/Qwen/Qwen3-0.6B-FP8/blob/main/LICENSE
- License quote: Model card front matter: 'license: apache-2.0 / license_link: https://huggingface.co/Qwen/Qwen3-0.6B-FP8/blob/main/LICENSE'; LICENSE file: 'Apache License Version 2.0, January 2004'
- Natural record: One FP8 weight tensor (one safetensors entry with dtype F8_E4M3), e.g. model.layers.N.mlp.down_proj.weight [1024,3072]
- Estimated samples: 196
- Estimated primary values: 440,401,920
- Estimated download bytes: 440,500,000
- Estimated primary bytes: 440,401,920
- Decode path: safetensors: 8-byte LE header length (59,128) + JSON header (dtype, shape, data_offsets) then raw tensor bytes. download.sh fetches the header (bytes 0-59135) and a single range covering data offsets 622,514,688..1,062,916,608 (+59,136 base), which skips the 622 MB of BF16 embed_tokens/lm_head stored first. build.sh (stdlib json + slicing) emits each F8_E4M3 tensor's bytes unchanged as one sample (FP8 codes are already the native typed values; no re-encoding). The interleaved BF16 weight_scale_inv block scales and norm vectors are excluded or emitted as auxiliary only. Validate: header dtype counts (196 F8_E4M3, 311 BF16), per-tensor byte length = prod(shape), pin sha256 of the range.
- Novelty kind: new_quantity
- Measurement type: nn_weights
- Instrument line: qwen3_llm_fp8
- Archive collection: huggingface.co/qwen
- Novelty evidence: novelty.py --url https://huggingface.co/Qwen/Qwen3-0.6B-FP8 --terms qwen fp8 float8 e4m3: same host only (other HF recipes); no recipe/registry/ledger/downstream term match. At 8-bit the only nn_weights families are smollm2_135m_q8_gguf_weights (local) and llama_q8_*/smollm2_135m_q8_* downstream, all GGUF Q8_0 two's-complement int8 block codes. FP8 E4M3 is a floating-point 8-bit representation (sign-exponent-mantissa bit fields) whose byte histogram and bit structure differ from symmetric int8. No FP8 family exists anywhere in the local or downstream corpus.
- Homogeneity: Single model, single quantization recipe (Qwen official fine-grained FP8, block 128, e4m3, per README quantization_config). Only F8_E4M3 tensors kept; 5 shape classes (3072x1024 x56, 1024x1024 x56, 1024x3072 x28, 1024x2048 x28, 2048x1024 x28), all linear weights under the same block-scale regime. No BF16 tensors mixed in.
- Risks: TOOLING: tools/audit_series_quality.FMT_MAP (used by gate.py) has no ('float', 8) entry, so gate.py will fail with 'unsupported numeric_kind/bit_width' unless a maintainer adds ('float',8):'B' (raw-byte degeneracy checks suffice, as for float16 'H'). Declaring uint instead would misstate the semantics; if the tooling cannot be extended the screener should mark needs_tooling rather than relabel. zlsim risk against Q8_0 int8 weights is low to moderate (different code space). Only one model, but 196 large natural tensors is ample.
- Probe evidence: HF API: model.safetensors size 1,062,975,744, license apache-2.0. Range GET bytes 0-7 -> header length 59128; range GET of JSON header parsed: 311 BF16 (622,514,688 B) + 196 F8_E4M3 (440,401,920 B); first F8 tensor model.layers.0.mlp.down_proj.weight offsets [622514688,625660416], last ends 1,062,916,608 = end of data. README: 'fine-grained fp8 quantization with block size of 128'.

Proposed by the autocollect scout on 2026-10-09 (transcript `.data/pipeline/logs/scout_8bit/scout.20261009_004435.jsonl`).
