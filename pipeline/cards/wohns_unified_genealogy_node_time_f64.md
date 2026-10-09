# Unified Genealogy of 1000 Genomes + HGDP + SGDP (Wohns et al. 2022, tsinfer+tsdate): Native Float64 Tree-Sequence Node Ages per Chromosome Arm

- Candidate id: `wohns_unified_genealogy_node_time_f64`
- Width: float64
- Quantity: Estimated age (generations before present) of every node in the inferred ancestral recombination graph, i.e. the tskit node table 'time' column (zarr dtype <f8), from tsdate posterior means. Sample nodes have time 0, about 1.8% of values.
- Source: https://zenodo.org/records/5495535
- Resources: https://zenodo.org/api/records/5495535, https://zenodo.org/records/5495535/files/hgdp_tgp_sgdp_chr16_p.dated.trees.tsz?download=1, https://zenodo.org/records/5495535/files/hgdp_tgp_sgdp_chr1_p.dated.trees.tsz?download=1
- License: CC-BY-4.0
- License evidence: https://zenodo.org/api/records/5495535
- License quote: "license": {"id": "cc-by-4.0"} (Zenodo record 5495535, 'A unified genealogy of modern and ancient genomes: Unified, inferred tree sequences of 1000 Genomes, Human Genome Diversity, and Simons Genome Diversity Projects', v1.0.0)
- Natural record: One chromosome-arm tree sequence: the full nodes/time array of one .trees.tsz file (39 files; 418k nodes for chr16_p, up to about 1M+ for large arms).
- Estimated samples: 39
- Estimated primary values: 29,000,000
- Estimated download bytes: 200,000,000
- Estimated primary bytes: 232,000,000
- Decode path: Stdlib plus the zstd CLI, the same dependency already used by the accepted MPC COG recipes. Each .tsz is a stored (method 0) zarr ZipStore. Read the zip CD via curl range requests, then range-fetch only 'nodes/time/.zarray' (JSON: blosc, cname zstd, shuffle 1, dtype <f8, a single chunk) and 'nodes/time/0'. Blosc frame: a 16-byte header (flags 0x91 = byteshuffle | dont-split | zstd, typesize 8, nbytes, blocksize, cbytes), then int32 block offsets. Each block is [int32 csize][zstd frame], decoded with 'zstd -dc' (or a memcpy if csize equals the raw size), followed by an 8-byte unshuffle and struct.unpack('<Nd'). Validated on chr16_p: 418,376 values, nbytes = shape*8.
- Novelty kind: new_modality
- Measurement type: genealogy_node_age
- Instrument line: tsinfer_tsdate_human_arg_inference
- Archive collection: zenodo.org
- Novelty evidence: novelty.py --url zenodo.org/records/5495535 matches the host only. Terms tsinfer/tsdate/genealogy/'tree sequence' match nothing in recipes, registry, ledger or downstream. --type genealogy_node_age returns 0. No population-genetic genealogy or ARG material exists at any width (genomic material in the corpus is sequence letters, quality scores, positions and methylation).
- Homogeneity: One release (v1.0.0, modern-only hgdp_tgp_sgdp *.dated.trees.tsz, not the ancients record 5512994), one inference pipeline (tsinfer + tsdate), one unit (generations), one field. One sample per chromosome arm (natural file boundary), taking all 39 arms. Do not mix in edges left/right (integer bp positions stored as f64, a widening) or other tables.
- Risks: (1) The values are model-inferred estimates, not direct instrument readings. They are a native typed output of a published genomic inference, which is fine under rule 2. (2) The recipe depends on the zstd CLI plus a small custom Blosc decoder, so the builder must self-test on synthetic Blosc frames. (3) Range-fetching zip members skips the whole-file Zenodo md5; validate via the zarray shape, the blosc nbytes, and the zip CRC32 in the CD. (4) Node order follows tsinfer ancestor ordering, so the sample is not monotonic. The leading block of zeros is the sample nodes (about 7.5k per file).
- Probe evidence: Zenodo API: 39 files totalling 3.45 GB, license cc-by-4.0. Range requests return 206. All 39 CDs were read: each has a single 'nodes/time/0' chunk. Compressed chunk sizes total 196 MB, from 1.33 MB (chr18_p) through a median of about 4.5 MB to the largest arms. I decoded the chr16_p chunk (2,810,126 bytes) fully: 418,376 doubles, min 0, max 81,718.57, 7,508 zeros, 0 NaN, 0 of 410,868 nonzero values f32-exact, 305,939 distinct.

Proposed by the autocollect scout on 2026-10-08 (transcript `.data/pipeline/logs/scout_64bit/scout.20261008_231914.jsonl`).
