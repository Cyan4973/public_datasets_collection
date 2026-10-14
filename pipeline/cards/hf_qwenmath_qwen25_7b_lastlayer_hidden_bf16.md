# Qwen Math Reasoning Hidden States: Qwen2.5-7B-Instruct Last-Layer Per-Generated-Token Hidden States on GSM8K and MATH-500 Traces, Native BFloat16

- Candidate id: `hf_qwenmath_qwen25_7b_lastlayer_hidden_bf16`
- Width: float16
- Quantity: Last-layer hidden state (3584-d) of Qwen2.5-7B-Instruct for every generated token (T ≤ 1024) of one sampled math solution trace
- Source: https://huggingface.co/datasets/lzhang472/qwen-math-hidden-states
- Resources: https://huggingface.co/api/datasets/lzhang472/qwen-math-hidden-states/tree/main?recursive=1, https://huggingface.co/datasets/lzhang472/qwen-math-hidden-states/resolve/1b8d08c6c6bca2c3ebad597f3ea0802c9d420910/manifest.jsonl, https://huggingface.co/datasets/lzhang472/qwen-math-hidden-states/resolve/1b8d08c6c6bca2c3ebad597f3ea0802c9d420910/mdl-qwen25_inst__ds-gsm8k__pid-gsm8k-1001__k0.safetensors
- License: Cache: Apache-2.0. Model Qwen/Qwen2.5-7B-Instruct: Apache-2.0. Prompts: openai/gsm8k (MIT) and MATH-500 (subset of hendrycks MATH via openai/prm800k, MIT). AIME 2024 traces are excluded.
- License evidence: https://huggingface.co/datasets/lzhang472/qwen-math-hidden-states/raw/1b8d08c6c6bca2c3ebad597f3ea0802c9d420910/README.md
- License quote: Card frontmatter: 'license: apache-2.0'. Qwen/Qwen2.5-7B-Instruct @a09a3545: 'license: apache-2.0'. openai/gsm8k @740312ad: license ['mit']. MATH-500 card: 'a subset of 500 problems from the MATH benchmark that OpenAI created in their Let's Verify Step by Step paper' (prm800k repo, MIT).
- Natural record: One sampled solution trace: the 'bytoken_lastlayer' BF16 tensor [T_gen, 3584] in mdl-qwen25_inst__ds-{gsm8k|math}__pid-*__k*.safetensors, emitted verbatim.
- Estimated samples: 600
- Estimated primary values: 970,000,000
- Estimated download bytes: 1,960,000,000
- Estimated primary bytes: 1,940,000,000
- Decode path: For each file: Range GET bytes 0-7 (u64 header length N), then bytes 8..7+N (JSON header). Range GET 8+N+data_offsets[0] .. 8+N+data_offsets[1]-1 for 'bytoken_lastlayer' and write it unchanged (BF16 LE). File discovery is the paginated tree API (Link rel=next) or manifest.jsonl x_path. Proposed bound: the first 300 gsm8k and 300 math traces of qwen25_inst in sorted path order (1,600 available).
- Novelty kind: new_modality
- Measurement type: llm_hidden_state
- Instrument line: qwen25_7b_instruct_lastlayer
- Archive collection: huggingface.co/lzhang472
- Novelty evidence: There are no LLM activation families locally or downstream. The only bf16 family is the Wan2.2 VAE latents (video_vae_latent), and 16-bit LLM content exists only as weights (SmolLM2/Pythia f16). This is native bf16, not fp16, so the exponent/mantissa byte split differs from the f16 caches, and post-final-layer generation states differ in distribution from weights and from mid-depth residuals.
- Homogeneity: One model (qwen25_inst only; exclude qwen3_inst and qwen3_think, which are different models), one tensor (bytoken_lastlayer; exclude bylayer_mean_gen and the random bytoken_proj), and two math word-problem sources with the same sampling protocol. If the judge wants one source, use GSM8K only (800 traces).
- Risks: (1) The card does not say whether the last-layer state is before or after the final RMSNorm (HF output_hidden_states[-1] for Qwen2 is post-norm); the probe range was about -99 to 179. (2) The math source MATH-500 has no license tag on the HF card itself; its MIT status comes from upstream prm800k/hendrycks. (3) The repo has 6,243 files, so discovery needs pagination. (4) It may be compression-similar to the Gemma candidate if both are accepted, but bf16 vs fp16-from-bf16 encodings should separate them.
- Probe evidence: Dataset API: sha 1b8d08c6c6bca2c3ebad597f3ea0802c9d420910, gated=False. Paginated tree counts: qwen25_inst gsm8k 800 files (2.11 GB), math 800 (3.84 GB), aime 480 (excluded). A safetensors header range-read of pid-gsm8k-1001__k0 returned bytoken_lastlayer BF16 [282,3584], offsets [207872, 2229248]. One token row decoded: min -99.5, max 179.0, 3 zeros, 1,357 distinct out of 3,584.

Proposed by the autocollect scout on 2026-10-14 (transcript `.data/pipeline/logs/scout_16bit/scout.20261014_130446.jsonl`).
