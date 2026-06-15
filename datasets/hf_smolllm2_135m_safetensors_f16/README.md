# HF SmolLM2 135M Safetensors F16

Collects native 16-bit floating-point model tensor payloads from the public
`HuggingFaceTB/SmolLM2-135M` `.safetensors` checkpoint.

The natural sample boundary is the safetensors tensor boundary. The build copies
each F16/BF16 tensor byte range unchanged into one raw sample file; tensors are
not concatenated or resampled.

```bash
datasets/hf_smolllm2_135m_safetensors_f16/download.sh
datasets/hf_smolllm2_135m_safetensors_f16/build.sh
datasets/hf_smolllm2_135m_safetensors_f16/verify.sh
```

Useful knobs:

- `MAX_FILE_BYTES=1000000000` rejects source checkpoints over the repository
  cap.
- `MODEL_URL=...`, `CONFIG_URL=...`, and `CARD_URL=...` can be overridden for a
  deterministic retry if upstream file locations move.

