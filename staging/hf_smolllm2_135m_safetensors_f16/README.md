# HF SmolLM2 135M Safetensors F16

Download-only staging recipe for the `HuggingFaceTB/SmolLM2-135M` model checkpoint.

The target material is native 16-bit floating-point model tensor payloads from a `.safetensors` checkpoint. Natural sample boundaries will be tensor boundaries after build; this download step only fetches and validates the checkpoint container.

Run:

```bash
staging/hf_smolllm2_135m_safetensors_f16/download.sh
staging/hf_smolllm2_135m_safetensors_f16/build.sh
staging/hf_smolllm2_135m_safetensors_f16/verify.sh
```

No payload is committed. Local files are written under `${DATA_DIR:-.data}`.
