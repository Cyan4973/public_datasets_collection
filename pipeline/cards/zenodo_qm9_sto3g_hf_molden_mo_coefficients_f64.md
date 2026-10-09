# QM9@STO-3G Hartree-Fock Molecular-Orbital Coefficient Matrices (PySCF Molden Files, King/Grzenda/Zhu 2025) Float64

- Candidate id: `zenodo_qm9_sto3g_hf_molden_mo_coefficients_f64`
- Width: float64
- Quantity: Restricted Hartree-Fock canonical molecular-orbital expansion coefficients in the STO-3G atomic-orbital basis (all occupied and virtual MOs), per QM9 molecule
- Source: https://zenodo.org/records/16934625
- Resources: https://zenodo.org/records/16934625/files/qm9_hfmoldens.zip?download=1, https://zenodo.org/api/records/16934625
- License: CC BY 4.0
- License evidence: https://zenodo.org/api/records/16934625
- License quote: Zenodo record 16934625 metadata: "license": {"id": "cc-by-4.0"}; description: '"qm9_hfmoldens" contains the molden files for the QM9@STO-3G dataset'.
- Natural record: One molecule's molden file gives one sample: the full [MO] block coefficients in file order (n_basis x n_basis; e.g. 55 x 55 = 3,025 values for a C8OH12 molecule), printed by PySCF 2.5.0 with 14 significant digits.
- Estimated samples: 7,000
- Estimated primary values: 20,000,000
- Estimated download bytes: 250,000,000
- Estimated primary bytes: 160,000,000
- Decode path: download.sh: curl -L -C - one contiguous byte-range prefix (~250 MB) of qm9_hfmoldens.zip (4,314,475,621 B, md5 b3ebb5bfe6409dc2edf8c1804d4ce780). Zenodo honours ranges (206 verified); retry on its intermittent 504s. build: walk the zip local file headers sequentially in pure Python (flag 0, so sizes sit in the local header; method 8 raw deflate, zlib.decompress(data,-15)) and keep complete members only. Parse each molden file: after the '[MO]' line, lines of the form '<idx> <coef>' are coefficients, and the Sym/Ene/Spin/Occup lines are skipped. Emit float64 LE per molecule. Verified on dsgdb9nsd_084221_sto-3g.molden: 55 MOs x 55 basis functions = 3,025 coefficients, range -0.85..1.36, values like 1.6252880766444e-07.
- Novelty kind: new_quantity
- Measurement type: molecular_orbital_coefficients
- Instrument line: PySCF 2.5.0 restricted Hartree-Fock, STO-3G basis
- Archive collection: zenodo
- Novelty evidence: novelty.py --url/--terms (molden, molecular orbital, sto-3g) finds no recipe, registry, ledger or downstream match (same host Zenodo only, different records). No orbital, Hamiltonian or wavefunction-coefficient family exists at any width (measurement_type molecular_orbital_coefficients: 0). The quantity is a dense orthonormal-transform matrix: sign-symmetric, many values near zero spanning ~10 decades, plus O(1) entries. That is unlike existing f64 time series, catalogs or point clouds.
- Homogeneity: One method (RHF/STO-3G via PySCF 2.5.0), one molecule set (QM9), one quantity (MO coefficients, dimensionless), one text format with fixed 14-significant-digit printing. Matrix size varies with molecule size but the generation process is identical.
- Risks: Per-sample size is modest (~3,000 values, ~24 KB), above the 1,000-value median floor but many small files; natural boundary is the molecule, do not concatenate. MO coefficients carry an arbitrary per-column sign (inherent). Zenodo occasionally returns 504 or a slow redirect, so download.sh needs retries. Zip member order is not sorted by QM9 index; the subset is 'first N members of the archive', which is deterministic and pinned by byte range and checksums of the extracted members.
- Probe evidence: Zenodo API record 16934625: cc-by-4.0, 4 files (qm9_hfmoldens.zip 4.31 GB). A range GET of bytes 0-262143 returned 206; local headers parsed: directory entry '../qm9_moldens/', then members dsgdb9nsd_084221_sto-3g.molden (33,920 compressed / 92,642 uncompressed bytes), 083217, 023587, 030867, 070327, all deflate with flag 0. The first member was inflated and its [Atoms], [GTO] and [MO] sections inspected.

Proposed by the autocollect scout on 2026-10-09 (transcript `.data/pipeline/logs/scout_64bit/scout.20261009_095410.jsonl`).
