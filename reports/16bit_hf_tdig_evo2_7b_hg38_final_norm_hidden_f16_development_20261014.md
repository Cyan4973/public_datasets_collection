# TDiG Evo 2 7B final-norm hidden-state float16 development

## Outcome

Accepted `hf_tdig_evo2_7b_hg38_final_norm_hidden_f16`. Each sample is the output of the final RMSNorm of the Evo 2 7B DNA language model (`arcinstitute/evo2_7b_base`, StripedHyena 2, 8K context) over one ~6 kb window of human reference hg38 chr22. That output is the representation fed to the unembedding. It is taken at 600 token positions (every 10th nucleotide) as a `(600, 4096)` float16 matrix.

This is the corpus's second hidden-state family. It is new content in a known modality, not a new modality: `hf_uq_gemma4_31b_mmlupro_residual_f16`, accepted the same day, opened the LLM hidden-state modality at 16 bits. The two differ in:

- model family: a convolutional/hyena DNA LM, not a text transformer;
- input: nucleotides, not text;
- tensor: the post-final-norm output, not a mid-depth residual stream.

zlsim measures them as statistically close but not compression-equivalent (distance 0.0334, loss 0.27).

## Source and rights

- Cache: Hugging Face dataset `darejinn/TDiG-evo2-hidden-states` at revision `9f0d2a6a31ddd08ca4e3defab714dc7665634501`. It is ungated and the card frontmatter says `license: mit`. The card's License section says "MIT (matches GitHub repo)". The GitHub repository `YAICON-8th-Think-Deep-in-Genome/TDiG` carries an MIT LICENSE.
- File: `chr22_tier3_raw.h5`, 47,677,466,172 bytes, LFS sha256 `26ae4008…98dc1`. The superblock EOF equals the pinned size.
- Model: `arcinstitute/evo2_7b_base` at `074097e9dc788e8bfe045d6495b9f6153a7c6bfc`, `license: apache-2.0`. Its card is pinned by sha256; no weights are fetched.
- Input: the UCSC hg38 reference assembly, a mosaic reference with no personal genotypes. The repository's ClinVar variant files are not fetched.
- download.sh re-checks both license lines, uses curl only, and passes no credentials.

## Shape and conversion

- Natural record: one genomic window, i.e. one Evo 2 forward pass. It is stored as `raw_h_norm[w]` of the HDF5 dataset `(100, 600, 4096)`: IEEE binary16 little-endian, contiguous, unfiltered, at address 471,870,248.
- Fetch: window `w` is bytes `[471,870,248 + w·4,915,200, +4,915,200)`, fetched by one HTTP Range GET (206 and the exact length required) and written verbatim. A pure-stdlib HDF5 reader (`scripts/h5meta.py`) re-derives the dtype, shape and layout from a 64 KiB head that is pinned by sha256.
- Representation: Evo 2 computes in bf16, and the publisher stored `h_norm` with `astype(np.float16)` (upstream `scripts/15_chr22_forward.py`). The low 3 mantissa bits are therefore zero except at fp16-subnormal magnitudes, giving about 13 effective bits with both bytes varying. This is the published artifact, the same representation as the accepted Gemma residual family.
- Selection: all 100 windows of the publisher's chr22 tier-3 subset, picked by `scripts/05_select_subset.py`. It takes the top 14 windows per context class (coding exon, intron, 5'/3' UTR, splice, intergenic), then fills with boundary-rich windows. The `window_idx` values run from 0 to 12883 of 12,978 non-N windows.
- Window overlap: upstream windows are 6 kb with a 3 kb step, so the 34 adjacent `window_idx` pairs overlap by half. Rows 300–599 of window w are the same positions as rows 0–299 of window w+1, computed with different left context. These rows are correlated (centered cosine 0.88–0.97) but are not duplicates: only 8–17% of codes are identical.
- Excluded: `chr17_tier3_raw.h5` (the same regime, another 491.5 MB), `raw_h_ell` (fp32), `raw_h_ell_rmsnormed`, tier-2 scalars and variant files.

## Accepted output

- Primary samples: 100, each `(600, 4096)` float16, 2,457,600 values (4,915,200 B)
- Primary values: 245,760,000
- Primary bytes: 491,520,000
- Download: 491,596,433 bytes on disk (the cards, the 64 KiB head, the 500-byte token_stride/done_mask span, and 100 window ranges)
- Value range: [-5.09375, 34.75], with no inf or NaN; 137 exact zeros
- Per-window rms: 0.4865–0.5183, carried mostly by outlier channel 3756 (13–34 in every row). Bulk |x|: p50 about 0.022, p99 0.65–0.75.
- Per window: 4,587–5,131 distinct codes, order-0 entropy 11.09–11.17 bits, row spread 0.0318–0.1290 (median 0.062), no duplicate rows
- Low-3 mantissa bits nonzero: 362,950 values (0.15%), all fp16-subnormal
- zlsim: verdict OK, own-compressor ratio 1.963, mode share 0.0014. Nearest is `hf_uq_gemma4_31b_mmlupro_residual_f16` (distance 0.0334, loss 0.27); next are `susy_lepton1_eta` (0.071) and `mast_jwst_nircam_sw_uncal_ramps_u16` (0.074, loss 0.051).

## Judge checks

- `gate.py`: PASS with no warnings (100 samples, median 2,457,600 values, width 16).
- `verify.sh` run by the judge: exit 0, "verify passed: 100 samples, 491520000 bytes", 55 s.
- build.sh and tdig_evo2.py read only local files. The only network I/O is in download.sh (curl), pinned to the revision.
- HDF5 decode, checked independently by scanning the head bytes:
  - float16 datatype message at offset 1760 (class 1, size 2, sign at bit 15, exponent 10/5, mantissa 0/10, bias 15);
  - dataspace (100, 600, 4096) at offset 1704;
  - layout v3 contiguous `(471870248, 491520000)` at offset 1810;
  - window_idx int64[100] at offset 2936, reading 0…12883.
- Bytes: I decoded nine windows spread across the window_idx range (0, 7, 13, 273, 1408, 3299, 5312, 9514, 12883). The distributions are consistent. Every value with nonzero low-3 bits is subnormal, which confirms bf16-in-fp16 storage and no local widening.
- Window order and overlap: a shift scan on five adjacent pairs gives a sharp peak at exactly 300 rows (cosine 0.88–0.97 against 0.0–0.3 elsewhere), and a non-adjacent control pair shows no peak. This confirms that the first-axis order matches `sorted(window_idx)` and that upstream windows overlap by 50%. The overlap is natural publisher structure, but the README does not document it.
- Rights: the HF API at the pinned revisions reports dataset `gated=False`, `license:mit` and model `license:apache-2.0`. I read the pinned card and the GitHub MIT LICENSE.
- Novelty: `novelty.py --url` matches only this draft. `--type`, `--instrument` and `--archive` return 0 matches. `--vocabulary` lists `llm_hidden_state` (the Gemma family), so the card's `new_modality` claim is downgraded to `new_content_same_modality`.
- Minor documentation staleness: the README's "Why this material" paragraph was written before the Gemma family was accepted. It still calls Gemma a staging draft and says no accepted recipe holds hidden states. The registry and this report carry the correct status.
- `scripts/__pycache__/` exists but is ignored by `.gitignore` (`__pycache__`).
