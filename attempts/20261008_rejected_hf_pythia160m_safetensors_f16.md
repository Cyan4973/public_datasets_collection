# hf_pythia160m_safetensors_f16

- Status: rejected
- Width: 16 (IEEE binary16)
- Source: https://huggingface.co/EleutherAI/pythia-160m/resolve/50f5173d932e8e61f858120bcb800b97af589f46/model.safetensors (374,998,696 bytes, LFS SHA-256 29d2e457a664e41c12c735f20a36dc0956a665f614a54ce5db21a32e75965270)
- License: Apache-2.0. The model card front matter has `license: apache-2.0` and the card says "License: Apache 2.0". The repo is not gated.

## What was done
- Recipe authored and downloaded (375 MB in 15 s).
- Build: a pure-stdlib safetensors parser takes the 50 F16 rank-2 weight matrices, emitted bit-identical as little-endian binary16.
  - embed_in and embed_out are 50304x768.
  - Each of the 12 layers contributes QKV, attention dense, h_to_4h and 4h_to_h.
  - Result: 162,201,600 values, 324,403,200 bytes, median sample 2,359,296 values.
- Values: no NaN/Inf, 20k–30k distinct binary16 words per tensor.
- build.sh, verify.sh and gate.py all PASS with no warnings.

## Why it failed
- `zlsim.py gate` verdict: WEAK (redundant).
  - Nearest match is downstream:susy_axial_met: distance 0.0113 (threshold 0.05), compressor loss 0.0005 (threshold 0.03).
  - downstream:susy_lepton1_eta is also redundant: distance 0.0153, loss 0.0.
  - Own compression ratio is only 1.18.
- The IEEE-f16 versus BF16 format difference did not make the bytes distinct. Near-Gaussian f16 weights compress like the existing downstream f16 physics-feature columns.
- Novelty was only new content in a known modality (nn_weights). The scout's prediction that the different exponent placement would separate it from existing families was wrong; the redundant match is a float16 physics family, not the BF16 SmolLM2 weights.

## Lessons
- Dense trained FP16 weight matrices are close to i.i.d. near-Gaussian floats at 16 bits, and the downstream SUSY f16 feature columns already cover that byte distribution. Other FP16 LLM checkpoints (pythia-410m, other GPT-NeoX or OPT models) are very likely WEAK as well.
