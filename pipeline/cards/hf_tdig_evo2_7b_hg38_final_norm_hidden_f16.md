# TDiG Evo 2 7B Genomic Language Model Final-Norm Hidden States over Human Reference hg38 chr22 and chr17 Windows, Native Float16

- Candidate id: `hf_tdig_evo2_7b_hg38_final_norm_hidden_f16`
- Width: float16
- Quantity: Final RMSNorm output hidden state h_norm (4096-d) of the Evo 2 7B DNA language model (arcinstitute/evo2_7b_base, 8K context) at 600 token positions (stride 10 bp) per hg38 genomic window
- Source: https://huggingface.co/datasets/darejinn/TDiG-evo2-hidden-states
- Resources: https://huggingface.co/datasets/darejinn/TDiG-evo2-hidden-states/resolve/9f0d2a6a31ddd08ca4e3defab714dc7665634501/chr22_tier3_raw.h5, https://huggingface.co/datasets/darejinn/TDiG-evo2-hidden-states/resolve/9f0d2a6a31ddd08ca4e3defab714dc7665634501/chr17_tier3_raw.h5
- License: Cache: MIT. Model arcinstitute/evo2_7b_base: Apache-2.0. Source sequence: UCSC hg38 human reference (GenBank-derived; NCBI places no restrictions on use).
- License evidence: https://huggingface.co/datasets/darejinn/TDiG-evo2-hidden-states/raw/9f0d2a6a31ddd08ca4e3defab714dc7665634501/README.md
- License quote: Card: 'license: mit' and '## License MIT (matches GitHub repo).' Provenance: 'Model: arcinstitute/evo2_7b_base revision 074097e9'; that model card (@074097e9) says 'license: apache-2.0'. 'Reference assembly: hg38 (UCSC)'. UCSC hg38 bigZips README: 'NCBI places no restrictions on the use or distribution of the GenBank data.'
- Natural record: One 8K-context genomic window: raw_h_norm[w] of shape (600, 4096) float16, i.e. 2,457,600 values (4.9 MB). There are 100 windows per chromosome file, all with done_mask = 1.
- Estimated samples: 200
- Estimated primary values: 491,520,000
- Estimated download bytes: 983,100,000
- Estimated primary bytes: 983,040,000
- Decode path: Pure-stdlib HDF5 walk via range reads, already validated on both files: superblock v0 → root symbol-table B-tree/SNOD → v1 object header of 'raw_h_norm'. That dataset is Dataspace (100, 600, 4096), Datatype float size 2, Layout v3 contiguous at address 471,870,248 with size 491,520,000, and no filter message (uncompressed). Both chr22 and chr17 have the same address and size. Window w = Range GET [471870248 + w*4915200, +4915200), written verbatim as little-endian float16. Read window_idx (contiguous at 2936, int64[100]) and token_stride (contiguous at 963390248, int32[100], all 10) for metadata.
- Novelty kind: new_modality
- Measurement type: genomic_lm_hidden_state
- Instrument line: evo2_7b_base_final_norm
- Archive collection: huggingface.co/darejinn
- Novelty evidence: There are no activation families anywhere locally or downstream (novelty.py --type/--archive: 0). Genome-related families are only 8-bit base sequences and MAPQ. This is a DNA foundation model's internal representation (StripedHyena 2), a different source model and content than any text LLM cache, so the byte statistics should differ from Gemma/Qwen text activations (spot check: rms ≈ 0.48 with a persistent outlier channel near +29).
- Homogeneity: One model, one tensor (raw_h_norm, the final-norm output), one reference genome, same window/stride protocol for both chromosomes. Exclude raw_h_ell (fp32), raw_h_ell_rmsnormed (a different, per-layer quantity), and the ClinVar variant files. If the judge prefers a single regime per chromosome, chr22 alone gives 100 samples and 491.5 MB.
- Risks: (1) The values are bf16 model outputs cast to fp16: in a 4,096-value probe the low 3 mantissa bits were nonzero in only 6 values, while the low byte varies (3,956 nonzero). This is effectively 13-bit MSB-aligned content and may draw a partial-hollowness objection. (2) The tensors sit in 47.7 GB HDF5 files, so the builder must use range reads; the offsets above were confirmed from the object headers. (3) The cache has a rare scientific-domain source (DNA), which is a strength for breadth but not proof of byte-level novelty; the zlsim gate still decides.
- Probe evidence: Dataset API: sha 9f0d2a6a31ddd08ca4e3defab714dc7665634501, gated=False, license mit. 64 KB head range GET showed HDF5 superblock v0, and a stdlib parser listed: raw_h_norm dims (100,600,4096), float size 2, contiguous (471870248, 491520000) in both chr22 and chr17. raw_h_ell_rmsnormed is chunked (1,32,600,4096). done_mask = 100/100, token_stride = 10. Three 8 KB range reads (windows 0, 57, 99) decoded to finite fp16 values: min about -2.4, max about 32, rms about 0.48-0.52, at most 1 zero.

Proposed by the autocollect scout on 2026-10-14 (transcript `.data/pipeline/logs/scout_16bit/scout.20261014_130446.jsonl`).
