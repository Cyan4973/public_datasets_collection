# SmolLM2-135M Q8_0 GGUF Quantized Weights

Int8 quantized model weights extracted from a **SmolLM2-135M-Instruct Q8_0 GGUF**, organized
as **one family per layer role** with **one sample per weight tensor** — "many tensor-series
of the same role". Fills a local gap: the downstream corpus has quantized-weight families
(`llama_q8_attn/embed/mlp`) but our collection had only f16 weights
(`hf_smolllm2_135m_safetensors_f16`).

- Source: https://huggingface.co/bartowski/SmolLM2-135M-Instruct-GGUF (Q8_0 GGUF, ~145 MB)
- Local raw payload: `${DATA_DIR:-.data}/downloads/smollm2_135m_q8_gguf_weights/model.gguf`

## Families & samples

| family | role | type |
|---|---|---|
| `gguf_q8_attn` | attention projections (q/k/v/output) | int8 |
| `gguf_q8_mlp` | feed-forward projections (gate/up/down) | int8 |
| `gguf_q8_embed` | token embedding | int8 |

- **A sample** = the int8 quantized values of one Q8_0 weight tensor.
- Only ggml type **Q8_0** tensors are used (the F32 norms are skipped). Each Q8_0 block holds
  a 2-byte fp16 scale + 32 signed int8 weights; the scale is dropped and the **32 int8 values
  are kept** (the quantized weights themselves).
- `attn` and `mlp` have one sample per tensor (~120 and ~90 tensors). `embed` is a single
  large tensor (~28M values) — retained because it far exceeds 1M values.

## Run

```sh
bash datasets/smollm2_135m_q8_gguf_weights/download.sh   # ~145 MB, resumable
bash datasets/smollm2_135m_q8_gguf_weights/build.sh
bash datasets/smollm2_135m_q8_gguf_weights/verify.sh
```

Tuning env vars: `GGUF_URL` (override the model), `GGUF_MIN_RECORDS` (default 1000),
`HF_UA`. The download is resumable (`curl -C -`, stall-based) and validates the GGUF magic.
Logs under `${DATA_DIR:-.data}/logs/smollm2_135m_q8_gguf_weights/`.
