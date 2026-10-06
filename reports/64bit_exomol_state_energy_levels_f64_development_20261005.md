# ExoMol state energy term values float64 development

## Outcome

Accepted `exomol_state_energy_levels_f64` from the version-pinned ExoMol
database (master file `exomol.all` version 20260605).

This is the first molecular-spectroscopy material in the corpus. Each sample
is the complete energy column of one isotopologue line list's `.states` file:
the term value E of every rovibronic state, in cm^-1 relative to the dataset's
lowest state. The source prints it as fixed six-decimal text (F12.6,
`%12.6f`).

Acceptance came after one repair cycle. The first build kept two line lists,
BH `10B-3H__AX` and NaO `23Na-16O__NaOUCMe`, whose energies were computed in
float32 and printed with six decimals. In those two files every token with
|E| >= 1024 cm^-1 equals the six-decimal print of the nearest float32, so
their effective lattice is the float32 ULP, not 1e-6. A pinned
`float32_lattice` whole-dataset rule now excludes both.

## Source and rights

- Source: official ExoMol file tree `https://www.exomol.com/db/`
- Master file: `exomol.all`, 189,391 bytes, SHA-256
  `3bc26ed45c5483839ee7a17ce4b135bdd5b2230147b6c261e07102884ffe646c`
  (102 molecules, 242 isotopologues, 250 datasets)
- `.def` files: 250, each SHA-256, size and state count pinned in
  `master_datasets.tsv`
- Selected payloads: 77 `.states.bz2` files (673,432,460 bytes) and 77
  `.def.json` files, with exact size, SHA-256, Last-Modified and decoded line
  count pinned in `sources.tsv`
- License: CC BY-SA 4.0. <https://www.exomol.com/data/licence/> says: "All
  data in ExoMol is released under the Creative Commons
  Attribution-ShareAlike 4.0 International (CC BY-SA 4.0) licence."
- Citation: Tennyson et al. 2024 (arXiv:2406.06347), plus the per-dataset
  DOI from each `.def.json`, or the ExoMol dataset-page reference where the
  DOI is missing. These are carried in `sources.tsv`, every index row and the
  manifest `dataset_citations`.

## Shape and conversion

- Selection: for each molecule in master order, take the first dataset whose
  `.def` declares 1,000 to 5,000,000 states. 77 molecules qualify. Neither
  the master file nor the `.def`/`.def.json` files carry a "recommended" flag,
  so master order is the documented tie-break.
- Natural record: one dataset's complete `.states` file. The sample is
  column 2 (E) in native state-ID order, which is a J/symmetry-block sawtooth.
- Conversion: each token is parsed to the nearest binary64, which equals the
  decimal micro-unit value divided by 10^6 and prints back to the token. No
  rescaling, sorting or deduplication. Up to 11 significant digits, which is
  beyond float32.
- Whole-dataset exclusion rules, pinned in `scripts/exomol_states.py` and per
  dataset in `sources.tsv` (reasons combine):
  - `def_count` (9): decoded line count differs from the `.def` count
  - `token_format` (4): `nan`, 5-decimal or free-format tokens
  - `id_sequence` (2): duplicated or out-of-order IDs
  - `lattice` (24): implied coarse-token share q_k above 0.02 + 5σ for
    k = 1, 2, 3
  - `float32_lattice` (2): at least 100 tokens with |E| >= 1024 and more
    than 5% equal to the six-decimal print of the nearest float32
  - `negative_reference` (0): more than 1% negative energies
- Not emitted: degeneracy, J, uncertainty, lifetime, Landé g, quantum labels,
  and the calculated-energy column of MARVELized files.

## Accepted output

- Datasets selected: 77; kept 43; excluded 34
- Primary samples: 43
- Primary values: 31,168,077
- Primary bytes: 249,344,616
- Minimum sample: 1,364 values (AlH AloHa)
- Median sample: 65,869 values
- Maximum sample: 4,968,160 values (NH3 CoYuTe)
- Value range: -0.146155 to 98,839.941885 cm^-1
- Aggregate decoded SHA-256 (samples concatenated in index order):
  `aa95a370df0f66202d939d3fd153ccf404b3c4d3b3bd40b7c667473fe7ae74ee`

## Judge checks

- `python3 tools/autocollect/gate.py staging/exomol_state_energy_levels_f64`:
  PASS, no warnings.
- Ran `verify.sh` myself: OK in 37 s, with the same totals. It re-hashes all
  77 downloads, re-parses them with an independent micro-unit parser,
  re-derives all 77 statuses and checks the index `f32_share`. `build.sh` reads
  only local files.
- Bytes: read all 43 samples with `struct`. No NaN or Inf; every value is an
  exact micro-unit; SHA-256 and counts match the index. My own bz2 parse of
  four sources (AlH, ScO, CH+, PN) matched with 0 mismatches.
- Float32 contamination: recomputed the f32 match count per kept sample (equal
  to the build's) and compared it with the chance rate 1e-6/ULP summed over
  each energy distribution. All |z| <= 2.7, so no dataset hides a partial
  float32 component below the 5% threshold. PF3's 0.0037 share is chance for
  its 1,024 to 5,915 cm^-1 range. The excluded BH and NaO files are 100%
  float32 prints.
- Last-digit chi-square: high only for CaO VBATHY and SO SOLIS (the
  documented ~1.5% coarse tokens, within the pinned lattice limit) and VO
  HyVO (an effect of repeated degenerate energies; it mostly vanishes among
  distinct values).
- README claims (31 of the other 40 kept within ±0.003, max kept f32 share
  0.003653, line totals 42,250,026 against 42,218,362 per the `.def` files)
  match `dataset_classification.tsv`.
- Rights: opened the ExoMol licence page myself; CC BY-SA 4.0 covers all
  ExoMol data. No credentials in any script; no personal data.
- Novelty: `novelty.py` (exomol.all URL; exomol, linelist, rovibronic,
  energy_level, spectroscop, wavenumber, HITRAN) matched only this candidate.
  The nearest neighbour, `figshare_rmd17_trajectories_f64`, is DFT
  molecular-dynamics material, not spectroscopic levels.
