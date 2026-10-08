# EleutherAI Pythia-160M (GPT-NeoX) Safetensors Weight Matrices, Native IEEE Float16

- Candidate id: `hf_pythia160m_safetensors_f16`
- Width: float16
- Quantity: Trained GPT-NeoX transformer parameter matrices (token embedding, unembedding, attention QKV/dense, MLP h_to_4h/4h_to_h) stored natively as IEEE-754 binary16. This is a different bit layout (5-bit exponent, 10-bit mantissa) from the corpus's BF16 SmolLM2 weights.
- Source: https://huggingface.co/EleutherAI/pythia-160m
- Resources: https://huggingface.co/EleutherAI/pythia-160m/resolve/50f5173d932e8e61f858120bcb800b97af589f46/model.safetensors
- License: Apache-2.0
- License evidence: https://huggingface.co/EleutherAI/pythia-160m/blob/main/README.md
- License quote: License: Apache 2.0 ... as long as your use is in accordance with the Apache 2.0 license.
- Natural record: One 2-D weight tensor: 48 per-layer matrices (12 layers x {query_key_value 2304x768, attention.dense 768x768, dense_h_to_4h 3072x768, dense_4h_to_h 768x3072}) plus embed_in and embed_out (50304x768 each). That is 50 samples of 0.59M-38.6M values. 1-D biases/norms and the U8 causal-mask buffers are excluded.
- Estimated samples: 50
- Estimated primary values: 162,000,000
- Estimated download bytes: 374,998,696
- Estimated primary bytes: 324,000,000
- Decode path: curl the pinned-revision model.safetensors (375 MB). Python reads the 8-byte header length and the JSON header (41 KB), selects the F16 tensors with 2-D shapes, and slices each tensor's data_offsets bytes, which are already little-endian binary16. Emit one sample per tensor unchanged. The header parse validates dtype F16, and the build rejects any BF16/F32.
- Novelty kind: new_content_same_modality
- Measurement type: nn_weights
- Instrument line: eleutherai_pythia_gptneox
- Archive collection: huggingface.co/eleutherai
- Novelty evidence: novelty.py --url huggingface.co/EleutherAI/pythia-410m --terms pythia eleutherai float16: no recipe, registry, ledger or downstream matches. nn_weights at 16 bits is only hf_smolllm2_135m_safetensors_f16, whose header shows 27 'BF16' dtypes (bfloat16 despite the id), plus downstream smollm_* splits of the same checkpoint. No IEEE-binary16 weights exist locally or downstream. The high byte of binary16 carries sign+5 exponent+2 mantissa bits instead of BF16's sign+7 exponent bits, so byte-lane statistics differ, but it is honestly the same modality.
- Homogeneity: One checkpoint, one dtype (F16), one tensor class (2-D matrices). The embedding/unembedding matrices are included as the same parameter type. Excluding the 1-D vectors keeps the median well above the floor and avoids mixing LayerNorm gains (values near 1) with the weight distributions.
- Risks: (1) The modality is not new: it is weights again, and only the number format differs from the BF16 family. The zlsim gate could rate it WEAK if the trained BF16 compressor transfers within 3%. That is unlikely given the different exponent placement, but possible. (2) Pythia was trained on the Pile. The Apache-2.0 grant covers the weights, but a judge may ask about training-data provenance (not a data-rights issue for the weights themselves). (3) Pythia-410m (911 MB F16) is an alternative with 98 matrices but sits near the 1 GB cap.
- Probe evidence: HF API: license apache-2.0, not gated, sha 50f5173d...; model.safetensors 374,998,696 bytes. A range read of the safetensors header showed 172 'F16' and 12 'U8' dtypes, with tensors such as gpt_neox.layers.0.attention.query_key_value.weight F16 [2304,768] and mlp.dense_4h_to_h.weight F16 [768,3072]. For comparison, the SmolLM2-135M header shows 27 'BF16'. pythia-410m resolves via 302 to the CDN with 200 and Content-Length 911,373,632.

Proposed by the autocollect scout on 2026-10-08 (transcript `.data/pipeline/logs/scout_16bit/scout.20261008_163746.jsonl`).
