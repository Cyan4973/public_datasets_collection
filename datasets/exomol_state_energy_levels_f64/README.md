# ExoMol Molecular State Energy Term Values (float64)

Status: staging draft. Download done; build and verify run against the
pinned files.

## What is collected

[ExoMol](https://www.exomol.com/) publishes computed and empirically refined
molecular line lists for hot astrophysical atmospheres. Each isotopologue
dataset has a `.states` file with one record per rovibronic state. Column 2 of
that file is the state energy term value `E` in cm^-1. Each dataset's
`.def.json` declares it as `"name": "E"`, `"ffmt": "F12.6"`,
`"cfmt": "%12.6f"`, "State energy in cm-1". Values carry up to 11
significant digits (for example `29170.834712`), which is beyond float32.

One sample is the complete energy column of one molecule's selected dataset,
in native file order (state ID order). ExoMol orders states by J and symmetry
block, so a sample is a sawtooth of ascending runs. Each token is parsed to
the nearest IEEE-754 binary64 and written little-endian. That double equals
the decimal micro-unit count divided by 10^6 and formats back to the source
token. Nothing is rescaled, sorted, or deduplicated.

Not emitted: degeneracy, J, uncertainty, lifetime, Lande g, quantum labels,
and the calculated-energy column of MARVELized files. The calculated energy
would be a second view of the same quantity.

## Selection (one dataset per molecule)

1. `exomol.all`, version `20260605` (SHA-256 pinned), lists 102 molecules,
   242 isotopologues and 250 datasets.
2. For each molecule, in master order, take the **first** dataset whose
   `.def` "No. of states in .states file" lies in [1,000, 5,000,000]. This
   gives 77 molecules. 25 molecules have no qualifying dataset: either every
   dataset has more than 5M states (e.g. CH4, H2CO, H2CS, SO3, HNO3, PH3,
   C2H4) or fewer than 1,000 (HeH+, HF, HBr, MgF, NaF, OH+, LiH+, H2+). One
   dataset per molecule avoids near-duplicate isotopologue copies of the same
   calculation.
3. Neither the master file nor the `.def`/`.def.json` files carry a
   "recommended" flag; only the HTML dataset pages do. Master order is
   therefore the documented rule. A consequence is that the chosen
   isotopologue is sometimes a minor one, e.g. HDO (VTT) for water and
   12C-13C (8states) for C2.

`master_datasets.tsv` pins every master entry: state count, dataset version,
`.def` URL, size and SHA-256. `sources.tsv` pins the 77 selected datasets:
URLs, `.states.bz2` size, Last-Modified, SHA-256 and decoded line count,
`.def.json` size and SHA-256, DOI or citation note, and the expected
keep/exclude status. `discover.sh` documents how both tables were resolved.
It uses metadata requests only and is not part of the download/build/verify
contract.

## Homogeneity and integrity rules

All kept samples must be one regime: a single unit (cm^-1) and a uniform
1e-6 cm^-1 decimal lattice, taken from a self-consistent file. As in the DCDB
off-lattice precedent, whole datasets are excluded by fixed rules. The
reasons combine.

- `def_count`: the decoded line count differs from the `.def`/`.def.json`
  "No. of states". The screener required these to match. Nine files
  disagree; in seven of them the IDs still run cleanly 1..L, so the `.def`
  metadata is stale or belongs to another file version. These are excluded
  rather than trusted.
- `token_format`: an energy token does not match `-?\d{1,6}\.\d{6}`.
  Examples: `nan` energies (AlO ATP), 5-decimal values above
  100,000 cm^-1 (H2 ARLR, OH MYTHOS), free-format tokens such as `0.0`
  (PS POPS). The declared C format `%12.6f` widens past 12 characters above
  100,000 cm^-1 while keeping six decimals, so width alone is not a
  violation.
- `id_sequence`: IDs are not strictly increasing from 1, i.e. duplicated
  (YO BRYTS) or out of order (MgO LiTY). Gaps in otherwise increasing IDs
  are **not** excluded. Seven kept datasets keep their original calculation
  numbering: AlCl YNAT, CaH XAB, MgH XAB, KH Khan, O2 SWYT, PN PaiN,
  SO SOLIS. Their line counts equal the `.def` counts, so they are complete;
  index rows carry `ids_contiguous`. This relaxes the literal "IDs run 1..N"
  wording of the screening note.
- `lattice`: on a uniform 1e-6 lattice, the share of tokens whose six-digit
  fraction ends in at least k zeros is p_k = 10^-k. With c_k such tokens
  out of n, the implied coarse-token share is
  q_k = (c_k/n - p_k)/(1 - p_k). The dataset is excluded if, for any
  k in {1, 2, 3}, q_k > 0.02 + 5·sqrt(p_k(1-p_k)/n)/(1-p_k). The
  threshold was fixed before the full data was seen. Excluded examples:
  datasets entirely on 1e-3 or 1e-4 grids (most MoLLIST sets), on a 1e-5
  grid (MgO LiTY, H2D+ ST, NO+ NOPE), and mixed ones (HCN Harris q1 = 0.09,
  CN, SO2 ExoAmes q1 = 0.22).
- `float32_lattice` (added in repair cycle 1): some line lists were
  computed in float32 and printed with `%12.6f`. Their effective lattice is
  the float32 ULP (1.22e-4 to 7.8e-3 cm^-1 between 1,024 and
  100,000 cm^-1), not 1e-6. Float32 decimal expansions rarely end in
  zeros, so the trailing-zero `lattice` test misses them. Over valid tokens
  with |E| >= 1024 cm^-1 (`FLOAT32_MIN_ABS`), count m eligible tokens and
  the f of them whose token equals the six-decimal print of the nearest
  float32, `'%.6f' % f32(v) == token`. A genuine 1e-6 value matches only by
  chance (at most about 1%). The dataset is excluded when
  m >= 100 (`FLOAT32_MIN_COUNT`) and f/m > 0.05 (`FLOAT32_SHARE_MAX`).
  Observed: BH 10B-3H AX and NaO NaOUCMe have share 1.000. Every kept
  dataset is at most 0.004 (largest PF3 MCYTY, 0.0037). Among datasets
  already excluded for other reasons the largest share is 0.047 (FeH
  MoLLIST), so none adds the new reason. Verify re-derives the rule from
  the integer micro-unit value with `decimal` (ROUND_HALF_EVEN) and checks
  the index `f32_share`.
- `negative_reference`: more than 1% negative energies. No dataset trips
  this. The single negative value among kept datasets (ScO LPB state 769,
  -0.146155 cm^-1, below the dataset's chosen zero) is kept verbatim.

Borderline kept datasets, all within the fixed `lattice` rule: CaO VBATHY
(q1 = q2 = 0.016, i.e. about 1.6% of energies on a 1e-4 grid, likely
MARVEL substitutions; 75% of its limit), SO SOLIS (q1 = 0.015) and KH Khan
(q2 = 0.010). Every other kept dataset has all q_k ≤ 0.013, and 31 of those
40 are within ±0.003. The largest deviations belong to the smallest files
(AlH AloHa and CH+ PYT, each under 1,600 states), where sampling noise
dominates; negative q values are deficits.

Statuses re-pinned in repair cycle 1 (all other 75 statuses unchanged):

- `10B-3H__AX`: `keep` -> `exclude:float32_lattice` (f32 share 1.000,
  1,075 of 1,075 eligible tokens)
- `23Na-16O__NaOUCMe`: `keep` -> `exclude:float32_lattice` (f32 share
  1.000, 35,816 of 35,816 eligible tokens)

`build.sh` classifies every selected dataset, writes
`filtered/<id>/dataset_classification.tsv` with the full statistics, and
fails if a realized status or line count differs from the values pinned in
`sources.tsv`. `verify.sh` re-hashes every download, re-derives every status
with an independent integer micro-unit parser, and checks:

- every stored double equals `micro / 10^6` and formats back to its token
- index fields, sample SHA-256, min/max, contiguity flags and `f32_share`
- at least 100 distinct values per sample
- floors, the 1 GB cap, and the manifest totals

`download.sh` re-derives the selection and every URL from the fetched master
file and `.def` files and fails on any mismatch. It checks exact sizes, the
pinned SHA-256 values and line counts, and each `.def.json` field layout
(ID I12, E F12.6). It decodes every `.states.bz2` in full and requires the
first record to have ID 1 and a finite energy. Large files use `curl -C -`
with stall-based limits. `EXOMOL_ALLOW_METADATA_DRIFT=1` tolerates a newer
master or a cosmetically changed `.def` only if the pinned selection and
state counts still re-derive exactly.

## Realized scope

- 77 datasets selected, **43 kept**, 34 excluded.
- **31,168,077 float64 values, 249,344,616 bytes**.
- Per sample: median 65,869 values, min 1,364 (AlH AloHa), max 4,968,160
  (NH3 CoYuTe).
- Value range -0.146155 to 98,839.941885 cm^-1.
- The eight largest datasets (NH3, CO2, CH3F, VO, PF3, CaOH, C3, OCS
  variational line lists) hold about 26M of the 31M values.

Kept datasets:

| Molecule | Isotopologue | Dataset | States | Max E (cm^-1) | Reference |
|---|---|---|---:|---:|---|
| AlCl | 27Al-35Cl | YNAT | 65,869 | 47999.863214 | doi:10.1093/mnras/stac3757 |
| AlH | 27Al-1H | AloHa | 1,364 | 29127.903725 | doi:10.1093/mnras/stad3802 |
| C2 | 12C-13C | 8states | 91,067 | 49183.634386 | doi:10.5281/zenodo.5716928 |
| C3 | 12C-12C-13C | AtLast | 2,442,205 | 16999.999777 | doi:10.1093/mnras/stae2425 |
| CaCl | 40Ca-35Cl | MoLLIST-CaCl | 9,060 | 26719.814452 | doi:10.3847/1538-4357/ad499e |
| CaH | 40Ca-1H | XAB | 6,825 | 29898.891328 | doi:10.1093/mnras/stac371 |
| CaO | 40Ca-16O | VBATHY | 130,660 | 48236.215392 | doi:10.5281/zenodo.5716731 |
| CaOH | 40Ca-16O-1H | OYT6 | 3,187,522 | 45200.042172 | doi:10.1093/mnras/stac2462 |
| CH3F | 12C-1H3-19F | OYKYT | 3,530,058 | 15999.294622 | doi:10.5281/zenodo.5716860 |
| CH+ | 12C-1H_p | PYT | 1,505 | 42125.728083 | doi:10.1093/mnras/stad3909 |
| CO | 12C-16O | 4thplus | 11,264 | 98839.941885 | see `citation_note` |
| CO2 | 12C-16O2 | Dozen | 3,646,814 | 35999.999193 | doi:10.1093/mnras/staf2135 |
| CS | 12C-32S | JnK | 11,497 | 66286.878662 | doi:10.5281/zenodo.5716944 |
| H2O | 1H-2H-16O | VTT | 163,491 | 29665.828269 | doi:10.5281/zenodo.5716812 |
| H2S | 1H2-32S | AYT2 | 220,630 | 34636.207111 | doi:10.5281/zenodo.5716826 |
| H3O+ | 1H3-16O_p | eXeL | 1,173,114 | 17999.992266 | doi:10.1093/mnras/staa2034 |
| HBO | 1H-10B-16O | LQL | 411,255 | 23999.986677 | doi:10.1039/D3CP05997A |
| KCl | 39K-35Cl | Barton | 60,741 | 30780.776050 | doi:10.5281/zenodo.5716977 |
| KH | 39K-1H | Khan | 13,081 | 39934.532129 | doi:10.1093/mnras/stag979 |
| LiOH | 6Li-16O-1H | OYT7 | 192,412 | 31899.459381 | doi:10.1093/mnras/stad3226 |
| MgH | 24Mg-1H | XAB | 3,148 | 29990.764285 | doi:10.1093/mnras/stac371 |
| NaCl | 23Na-35Cl | Barton | 48,937 | 37371.896310 | doi:10.5281/zenodo.5717023 |
| NaH | 23Na-1H | Rivlin | 3,339 | 37099.471916 | doi:10.5281/zenodo.5363263 |
| NH3 | 14N-1H2-2H | CoYuTe | 4,968,160 | 17999.999275 | doi:10.1093/mnras/stag462 |
| NO | 14N-16O | XABC | 30,811 | 62999.953525 | doi:10.5281/zenodo.5716782 |
| NS | 14N-32S | SNaSH | 31,502 | 38918.888924 | doi:10.5281/zenodo.5717011 |
| O2 | 16O-17O | SWYT | 22,387 | 40588.944059 | see `citation_note` |
| OCS | 16O-12C-32S | OYT8 | 2,399,110 | 19999.996581 | doi:10.1093/mnras/stae1110 |
| PF3 | 31P-19F3 | MCYTY | 3,311,926 | 5914.726631 | doi:10.5281/zenodo.5716880 |
| PH | 31P-1H | LaTY | 2,528 | 28296.189596 | doi:10.5281/zenodo.5716703 |
| PN | 31P-14N | PaiN | 30,327 | 82498.772121 | doi:10.1093/mnras/stae2610 |
| PO | 31P-16O | POPS | 43,148 | 48496.178742 | doi:10.5281/zenodo.5716784 |
| ScH | 45Sc-1H | LYT | 8,451 | 15812.558195 | doi:10.5281/zenodo.5363276 |
| ScO | 45Sc-16O | LPB | 73,384 | 32186.143665 | doi:10.3847/1538-4357/ad7af1 |
| SH | 32S-1H | GYT | 7,686 | 37642.777949 | doi:10.5281/zenodo.5716705 |
| SiH | 28Si-1H | SiGHTLY | 11,785 | 32399.734806 | doi:10.5281/zenodo.5716715 |
| SiH2 | 28Si-1H2 | CATS | 593,804 | 19999.994395 | doi:10.5281/zenodo.5716836 |
| SiO | 28Si-16O | SiOUVenIR | 174,250 | 71999.303465 | doi:10.5281/zenodo.5910818 |
| SiS | 28Si-32S | UCTY | 10,104 | 36807.754399 | doi:10.5281/zenodo.5717037 |
| SO | 32S-16O | SOLIS | 84,114 | 45496.584953 | doi:10.1093/mnras/stad3508 |
| TiO | 46Ti-16O | Toto | 301,026 | 55661.994078 | doi:10.5281/zenodo.5716754 |
| VO | 51V-16O | HyVO | 3,410,598 | 45067.457094 | doi:10.1093/mnras/stae542 |
| ZrO | 90Zr-16O | ZorrO | 227,118 | 63103.230223 | doi:10.1093/mnras/stad2103 |

Excluded datasets:

| Molecule | Dataset | Reason | Detail |
|---|---|---|---|
| AlF | 27Al-19F__MoLLIST | lattice | q1/q2/q3 = 1.000/0.088/0.010 |
| AlO | 26Al-16O__ATP | token_format | 76 bad tokens, e.g. `nan` |
| AsH3 | 75As-1H3__CYT18 | def_count | 4,319,856 lines vs .def 4,319,868 |
| BeH | 9Be-1H__Darby-Lewis | lattice | q1/q2/q3 = 0.038/0.003/0.000 |
| BH | 10B-3H__AX | float32_lattice | f32 share 1.000 (1,075 of 1,075 tokens with abs(E) >= 1024; 1,090 states) |
| CaF | 40Ca-19F__MoLLIST | lattice | q1/q2/q3 = 1.000/1.000/0.108 |
| CH | 12C-1H__MoLLIST | def_count+lattice | 2,680 lines vs .def 2,681; q1/q2/q3 = 1.000/0.090/0.010 |
| CN | 12C-14N__KTPSYT | def_count+lattice | 27,965 lines vs .def 28,004; q1/q2/q3 = 0.218/0.019/0.002 |
| CP | 12C-31P__MoLLIST | lattice | q1/q2/q3 = 1.000/1.000/0.102 |
| CrH | 52Cr-1H__MoLLIST | lattice | q1/q2/q3 = 1.000/1.000/1.000 |
| FeH | 56Fe-1H__MoLLIST | def_count+lattice | 3,960 lines vs .def 3,564; q1/q2/q3 = 1.000/1.000/1.000 |
| H2 | 1H2__ARLR | token_format | 1581 bad tokens, e.g. `100842.91000` |
| H3+ | 1H2-2H_p__ST | lattice | q1/q2/q3 = 0.997/0.090/0.009 |
| HCl | 2H-35Cl__HITRAN-HCl | lattice | q1/q2/q3 = 0.264/0.265/0.028 |
| HCN | 1H-12C-14N__Harris | lattice | q1/q2/q3 = 0.089/0.008/0.001 |
| KF | 39K-19F__MoLLIST | lattice | q1/q2/q3 = 0.127/0.126/0.012 |
| LaO | 139La-16O__BDL | def_count+lattice | 63,664 lines vs .def 63,644; q1/q2/q3 = 1.000/1.000/0.097 |
| LiCl | 6Li-35Cl__MoLLIST | lattice | q1/q2/q3 = 1.000/1.000/1.000 |
| LiF | 6Li-19F__MoLLIST | lattice | q1/q2/q3 = 1.000/1.000/1.000 |
| LiH | 7Li-1H__CLT | lattice | q1/q2/q3 = 1.000/1.000/0.102 |
| MgO | 24Mg-16O__LiTY | id_sequence+lattice | q1/q2/q3 = 0.920/0.084/0.008; IDs duplicated or out of order |
| N2 | 14N2__WCCRMT | def_count | 58,380 lines vs .def 40,380 |
| N2O | 14N-15N-16O__TYM | def_count | 2,197,105 lines vs .def 2,183,803 |
| NaO | 23Na-16O__NaOUCMe | float32_lattice | f32 share 1.000 (35,816 of 35,816 tokens with abs(E) >= 1024; 36,120 states) |
| NH | 14N-1H__2kNigHt | lattice | q1/q2/q3 = 0.254/0.025/0.005 |
| NiH | 58Ni-1H__BYOT | lattice | q1/q2/q3 = 0.028/0.029/0.030 |
| NO+ | 14N-16O_p__NOPE | lattice | q1/q2/q3 = 0.937/0.082/0.008 |
| OH | 16O-1H__MYTHOS | token_format | 6855 bad tokens, e.g. `100414.17404` |
| PS | 31P-32S__POPS | token_format | 23140 bad tokens, e.g. `0.0` |
| S2 | 32S2__Gomez | lattice | q1/q2/q3 = 0.139/0.139/0.014 |
| SiN | 28Si-14N__SiNfull | def_count | 131,935 lines vs .def 131,936 |
| SO2 | 32S-16O2__ExoAmes | def_count+lattice | 3,270,270 lines vs .def 3,270,271; q1/q2/q3 = 0.220/0.020/0.002 |
| TiH | 48Ti-1H__MoLLIST | lattice | q1/q2/q3 = 1.000/1.000/1.000 |
| YO | 89Y-16O__BRYTS | id_sequence+lattice | q1/q2/q3 = 0.025/0.013/0.001; IDs duplicated or out of order |

## License and citation

All ExoMol data is released under **CC BY-SA 4.0**
(<https://www.exomol.com/data/licence/>): "All data in ExoMol is released
under the Creative Commons Attribution-ShareAlike 4.0 International (CC
BY-SA 4.0) licence." ExoMol requests citation of the relevant journal
articles. Derived samples must remain CC BY-SA 4.0 with attribution.

- Database: J. Tennyson et al., "The 2024 release of the ExoMol database:
  molecular line lists for exoplanet and other hot atmospheres", JQSRT
  (2024), arXiv:2406.06347.
- Per dataset: the DOI from each `.def.json` (table above; `doi` column of
  `sources.tsv`; every index row; manifest `dataset_citations`). The `.def`
  text files themselves contain no citation. Where `.def.json` has no usable
  DOI (CO 4thplus, NO+ NOPE, O2 SWYT, HCl HITRAN-HCl), `citation_note`
  records the reference listed on the ExoMol dataset page.

## Files

- `download.sh`, `build.sh`, `verify.sh`: script contract; honour `DATA_DIR`
  and log to `$DATA_DIR/logs/exomol_state_energy_levels_f64/`.
- `scripts/exomol_states.py`: pure-stdlib helper (plan, validate, build,
  verify, discover, selected).
- `master_datasets.tsv`, `sources.tsv`: pinned resolution tables.
- `discover.sh`: metadata-only resolution record.
