# uq-hiddenstates: Gemma-4-31B-it Residual-Stream States at Relative Depth 0.75 (block 45 of 60) over MMLU-Pro Reasoning Traces, Native Float16

- Candidate id: `hf_uq_gemma4_31b_mmlupro_residual_f16`
- Width: float16
- Quantity: Raw, unnormalized residual-stream hidden state (output of decoder block 44, hidden index 45) at every token position of one Gemma-4-31B-it reasoning trace (prompt + generated chain of thought + answer), 5376 values per token
- Source: https://huggingface.co/datasets/loose-bits/uq-hiddenstates
- Resources: https://huggingface.co/datasets/loose-bits/uq-hiddenstates/resolve/853e3392729d5ecc5663e4a635898085acc92109/gemma_mmlupro_L45.idx.json, https://huggingface.co/datasets/loose-bits/uq-hiddenstates/resolve/853e3392729d5ecc5663e4a635898085acc92109/gemma_mmlupro_L45.part00.npy, https://huggingface.co/datasets/loose-bits/uq-hiddenstates/resolve/853e3392729d5ecc5663e4a635898085acc92109/gemma_mmlupro_L45.part01.npy
- License: Cache: Apache-2.0. Model google/gemma-4-31B-it: Apache-2.0. Source prompts TIGER-Lab/MMLU-Pro: MIT.
- License evidence: https://huggingface.co/datasets/loose-bits/uq-hiddenstates/raw/853e3392729d5ecc5663e4a635898085acc92109/README.md
- License quote: Cache card frontmatter: 'license: apache-2.0'. Gemma 4 model card (google/gemma-4-31B-it @842da379) has 'license: apache-2.0' with license_link https://ai.google.dev/gemma/docs/gemma_4_license, a page titled 'Apache License 2.0 | Gemma'. TIGER-Lab/MMLU-Pro @b189ec76 has 'license: mit'.
- Natural record: One reasoning trace (one MMLU-Pro item): the contiguous row block [off, off+n) of the fp16 [rows, 5376] npy shard named in gemma_mmlupro_L45.idx.json. The index guarantees no trace spans two shards. Output is the [n, 5376] float16 matrix, written verbatim.
- Estimated samples: 48
- Estimated primary values: 868,900,000
- Estimated download bytes: 1,740,000,000
- Estimated primary bytes: 1,737,800,000
- Decode path: Fetch the idx.json (138 KB). Read the npy header (128 bytes; '<f2', C order, shape (1995868, 5376) for part00). For each selected item, HTTP Range GET bytes 128 + off*10752 .. 128 + (off+n)*10752 - 1 from its shard and write them unchanged as little-endian float16. Only stdlib json, struct and curl are needed. Proposed bound: the first 48 items of the index in order (all in shard 0; median n = 2347 tokens, so about 25 MB each).
- Novelty kind: new_modality
- Measurement type: llm_hidden_state
- Instrument line: gemma4_31b_it_resid_l45
- Archive collection: huggingface.co/loose-bits
- Novelty evidence: novelty.py --url matches the huggingface.co host only (weights, VAE latents, tokens). There are no activation or hidden-state families locally or downstream; the 16-bit float families are OpenEXR, Hypersim normals, SmolLM2 and Pythia weights, and the Wan2.2 VAE latents. Residual-stream activations of a 31B LLM have very heavy-tailed outlier channels ('massive activations'), unlike weights (near-Gaussian) or VAE latents.
- Homogeneity: One model (gemma-4-31B-it), one layer (hidden index 45), one source dataset (MMLU-Pro), one generation setup (seeded stratified sample, one trace per item). Do not mix in the other datasets in the repo (logiqa2, supergpqa, omnimath, lcb, triviaqa), the olmo/qwen35 files, or the *_k64 projections.
- Risks: (1) The fp16 values are bf16 model outputs cast to fp16 by the publisher. A probe of 10,752 values found the low 3 mantissa bits nonzero in only 2, while the low byte varies (10,297 nonzero). This is effectively 13-bit content MSB-aligned in 16 bits, like the accepted TUM VI 12-bit frames, but a judge may call it partially hollow. (2) Each sample is large (about 25 MB, up to ~170 MB for the longest traces), so pick the 48 deterministically. (3) Generated reasoning tokens are the model's own output; the content chain is only Gemma 4 (Apache) and MMLU-Pro (MIT). (4) The repo's lastModified is 2026-09-21; pin revision 853e3392.
- Probe evidence: Dataset API: sha 853e3392729d5ecc5663e4a635898085acc92109, gated=False. Tree: gemma_mmlupro_L45.part00.npy 21,459,572,864 B and part01 14,746,378,880 B. idx.json: model gemma, li 45, L 60, hidden 5376, 1000 items, 3,367,369 tokens, n min 394 / median 2347 / max 16172; shards part00 1,995,868 rows and part01 1,371,501 rows. Range GET of the npy header returned {'descr': '<f2', 'fortran_order': False, 'shape': (1996476, 5376)} (omnimath part00; same format). A range-read row slice of the mmlupro shard decoded to finite fp16 values (1,894 distinct out of 10,752).

Proposed by the autocollect scout on 2026-10-14 (transcript `.data/pipeline/logs/scout_16bit/scout.20261014_130446.jsonl`).
