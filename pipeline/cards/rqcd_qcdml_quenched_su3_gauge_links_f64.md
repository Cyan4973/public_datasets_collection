# RQCD qcdML Quenched SU(3) Lattice-QCD Gauge Configurations (ens_001, 8^3x16, Wilson beta=6.0, heat-bath): Native Complex128 Link Matrices Float64

- Candidate id: `rqcd_qcdml_quenched_su3_gauge_links_f64`
- Width: float64
- Quantity: SU(3) gauge link matrix elements U_mu(x) (real and imaginary parts, dimensionless, |entries|<=1) of a quenched Wilson-plaquette Markov chain at beta=6.0; shape (4,8,8,8,16,3,3) complex128 per configuration
- Source: https://zenodo.org/records/15018324
- Resources: https://zenodo.org/api/records/15018324/files/ens_001_pt.zip/content, https://zenodo.org/records/17494830, https://zenodo.org/api/records/17494830/files/ens_004_selected.tar/content
- License: CC-BY-4.0
- License evidence: https://zenodo.org/records/15018324
- License quote: Zenodo record metadata for 'ldg/rqcd/qcdML/ens_001' (and sibling 'mc://ldg/rqcd/qcdML/ens_004_selected', record 17494830): license id 'cc-by-4.0' (Creative Commons Attribution 4.0 International); creator Daniel Knüttel, University of Regensburg
- Natural record: One gauge configuration (one Markov-chain sample) = one torch .pt member config_<n>.pt holding a single ComplexDoubleStorage tensor of 294,912 complex = 589,824 float64 values
- Estimated samples: 150
- Estimated primary values: 88,473,600
- Estimated download bytes: 680,000,000
- Estimated primary bytes: 707,788,800
- Decode path: download.sh: range-GET the zip tail (Zip64 EOCD + central directory, under ~1 MB), parse it with stdlib struct to get each config_<n>.pt local-header offset and compressed size, then curl -r each selected member (deflate, about 4.51 MB each) with evenly spaced config numbers (e.g. every ~30th along the chain, about 150 configs). build: zlib.decompressobj(-15) to get the inner .pt (itself a stored zip): zipfile reads <name>/data.pkl and <name>/data/0. Validate the tensor header with pickletools.genops (no unpickling): ComplexDoubleStorage, shape (4,8,8,8,16,3,3), contiguous. Emit data/0 as little-endian f64 (re,im interleaved). Optional check: each 3x3 is unitary to ~1e-12.
- Novelty kind: new_modality
- Measurement type: lattice_gauge_configuration
- Instrument line: rqcd_qcdml_quenched_wilson_beta6_heatbath
- Archive collection: zenodo
- Novelty evidence: novelty.py --url https://zenodo.org/records/17494830 --terms qcdML rqcd gauge Knüttel: no URL match and no lattice/QCD term hits in datasets, staging, registry, ledger or downstream (only unrelated 'gauge' = water-gauge hits). The vocabulary has no lattice-field-theory or Monte-Carlo-configuration type; --type lattice_gauge_configuration returns 0 members.
- Homogeneity: A single Markov chain: one action (Wilson plaquette, beta=6.0), one lattice (8^3x16), one algorithm (SU(2)-subgroup heat bath), one representation (complex128 SU(3) matrices). All samples share the same value distribution. Keep ens_004 (16^3x32, HMC, 10 configs, 75.5 MB each, stored tar) out of this family, or use it only as a fallback, so that lattice volume and algorithm are not mixed.
- Risks: (1) The download needs Zip64 central-directory parsing and per-member range requests, which are builder complexity. The tail probe already parsed 2,810 central-directory entries from the last 300 KB. (2) Successive heat-bath configs are correlated, so pick widely spaced config numbers. (3) Link entries are near-random full-mantissa doubles (deflate ratio 0.956). That is good for breadth, but the judge may call the material high-entropy noise; it is genuine first-principles simulation output. (4) The .pt pickle must not be unpickled; parse with pickletools only. (5) Per-member deflate, so a few bytes beyond compressed size must be fetched correctly (local header plus name/extra lengths).
- Probe evidence: ens_004 tar: range GET bytes 0-4095 gave member ens_004_selected/config_282.pt, size 75,498,731 (octal 440002353). The inner zip local header is config_282/data.pkl; the pickle shows torch._utils._rebuild_tensor_v2, ComplexDoubleStorage, shape (4,16,16,16,32,3,3) = 4,718,592 complex128 = 75,497,472 bytes. ens_001 zip: range GET of the last 300 KB parsed 2,810 central-directory entries, e.g. ens_001_pt/config_2973.pt method 8, csize 4,514,138, usize 4,719,856 (= 589,824 f64 + .pt overhead), plus ens_001_pt/metadata.yml. Record metadata: 8x8x8x16, beta 6.0, SU(2) heat bath; file size 22,571,455,882.

Proposed by the autocollect scout on 2026-10-09 (transcript `.data/pipeline/logs/scout_64bit/scout.20261009_102323.jsonl`).
