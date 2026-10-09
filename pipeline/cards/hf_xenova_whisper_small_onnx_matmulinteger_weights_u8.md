# Whisper-small (OpenAI) ONNX Dynamic-Quantized Transformer Weights: Per-Tensor Asymmetric UInt8 MatMulInteger Weight Tensors (Xenova Transformers.js export)

- Candidate id: `hf_xenova_whisper_small_onnx_matmulinteger_weights_u8`
- Width: uint8
- Quantity: Speech-recognition encoder/decoder linear-layer weights quantized per tensor to uint8 with a per-tensor scale and zero point (onnxruntime quantize_dynamic, QUInt8); one value = one quantized weight code
- Source: https://huggingface.co/Xenova/whisper-small
- Resources: https://huggingface.co/Xenova/whisper-small/resolve/main/onnx/encoder_model_uint8.onnx, https://huggingface.co/Xenova/whisper-small/resolve/main/onnx/decoder_model_uint8.onnx, https://huggingface.co/Xenova/whisper-small/resolve/main/onnx/decoder_model_merged_uint8.onnx
- License: Apache-2.0 (Xenova export card; base model openai/whisper-small also apache-2.0)
- License evidence: https://huggingface.co/Xenova/whisper-small/blob/main/README.md
- License quote: README front matter: 'base_model: openai/whisper-small / library_name: transformers.js / license: apache-2.0'; HF API cardData license for openai/whisper-small: apache-2.0
- Natural record: One quantized weight initializer (TensorProto, data_type UINT8) consumed as input B of a MatMulInteger node, e.g. onnx::MatMul_2010_quantized [768x768] or fc1 [768x3072]
- Estimated samples: 190
- Estimated primary values: 200,000,000
- Estimated download bytes: 410,000,000
- Estimated primary bytes: 200,000,000
- Decode path: Pure-stdlib protobuf wire-format walker (varints + length-delimited fields): ModelProto field 7 (graph) -> GraphProto field 1 nodes (op_type field 4, inputs field 1) and field 5 initializers (dims 1, data_type 2, name 8, raw_data 9). Keep initializers with data_type==2 (UINT8) that feed MatMulInteger input B (names ending '_quantized'); emit raw_data unchanged; scale/zero_point initializers are auxiliary. Prefer encoder_model_uint8.onnx + decoder_model_uint8.onnx (plain graphs); if the merged decoder is used, walk If-node subgraph attributes (AttributeProto field 6 'g') and de-duplicate by name. Validate len(raw_data) == prod(dims).
- Novelty kind: new_content_same_modality
- Measurement type: nn_weights
- Instrument line: whisper_asr_onnx_uint8
- Archive collection: huggingface.co/xenova
- Novelty evidence: novelty.py --url https://huggingface.co/Xenova/whisper-small --terms whisper onnx matmulinteger xenova: same host only; no term matches in recipes, registry, ledger or downstream. Existing 8-bit weights (smollm2_135m_q8_gguf_weights, downstream llama_q8_*, smollm2_135m_q8_*) are GGUF Q8_0: symmetric int8 per 32-value block, which spreads codes over the full -127..127 range in every block. These are asymmetric per-tensor uint8 codes centred on a zero point around 100, with a narrow peaked spread (one scale per whole matrix, so outliers set the range), from a different architecture (audio encoder-decoder) and toolchain (onnxruntime). Expected byte statistics differ, but the modality is the same, hence the honest label.
- Homogeneity: One model, one quantization tool and setting (dynamic QUInt8 per-tensor), only MatMulInteger weight tensors (encoder 72 = 12 layers x {q,k,v,o,fc1,fc2}; decoder self/cross attention + MLP). Float initializers (conv1/conv2 frontend, layer norms, biases, positional embeddings) excluded. Each tensor has its own zero point, which is intrinsic to per-tensor quantization (one regime).
- Risks: Same modality as an accepted 8-bit family (nn_weights), so acceptance depends on zlsim seeing per-tensor uint8 statistics as distinct from Q8_0 int8; moderate WEAK risk. ONNX files cannot be range-subset, but the total download is only ~0.25-0.41 GB. The merged decoder uses If subgraphs; use the non-merged files to avoid duplicates. decoder_model_uint8.onnx (315 MB) may hold a float embedding that must not be emitted.
- Probe evidence: HF API sizes: encoder_model_uint8.onnx 92 MB, decoder_model_uint8.onnx 315 MB, decoder_model_merged_uint8.onnx 156 MB. Range GET 0-3 MB of encoder parsed with the stdlib protobuf walker: op counts MatMulInteger 72, DynamicQuantizeLinear 50. Range GET of the tail at 89-92.5 MB shows initializer triplets 'onnx::MatMul_2010_scale', '..._zero_point', '..._quantized', followed by raw weight bytes concentrated in 0x50-0x75 (uint8 around the zero point).

Proposed by the autocollect scout on 2026-10-09 (transcript `.data/pipeline/logs/scout_8bit/scout.20261009_004435.jsonl`).
