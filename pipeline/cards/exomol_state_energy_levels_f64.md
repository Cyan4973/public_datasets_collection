# ExoMol Molecular Line-List State Energy Term Values (.states, cm^-1) Float64

- Candidate id: `exomol_state_energy_levels_f64`
- Width: float64
- Quantity: Rovibronic state energy term values in cm^-1 (column 2, Fortran f12.6, of ExoMol .states files) of computed/empirically refined molecular line lists. Values reach 11-12 significant digits, e.g. 29170.834712.
- Source: https://www.exomol.com/data/molecules/
- Resources: https://www.exomol.com/db/exomol.all, https://www.exomol.com/db/AlCl/27Al-35Cl/YNAT/27Al-35Cl__YNAT.def, https://www.exomol.com/db/AlCl/27Al-35Cl/YNAT/27Al-35Cl__YNAT.states.bz2, https://www.exomol.com/db/H2O/1H2-16O/POKAZATEL/1H2-16O__POKAZATEL.states.bz2, https://www.exomol.com/data/licence/
- License: CC-BY-SA-4.0
- License evidence: https://www.exomol.com/data/licence/
- License quote: All data in ExoMol is released under the Creative Commons Attribution-ShareAlike 4.0 International (CC BY-SA 4.0) licence
- Natural record: One ExoMol isotopologue dataset's complete .states file; the sample is its full energy column, in file order. Suggested scope: one dataset per molecule (first listed in exomol.all that has 1,000-5,000,000 states), giving 73 datasets, median 31,502 states, min 1,065, max 4,968,160.
- Estimated samples: 73
- Estimated primary values: 41,006,532
- Estimated download bytes: 640,000,000
- Estimated primary bytes: 328,052,256
- Decode path: Pure stdlib. Parse exomol.all (master file, version 20260605, 250 datasets) for molecule/iso-slug/dataset paths. Fetch each <iso>__<ds>.def (gives 'No. of states' to pin counts) and <iso>__<ds>.states.bz2. Decompress with bz2.BZ2Decompressor, split lines, take whitespace field 2 (energy, f12.6) and parse with float() to struct '<d'. Verify the line count equals the .def state count and IDs are 1..N.
- Novelty kind: new_modality
- Novelty evidence: novelty.py for the exomol.com db URL with terms exomol/spectroscopic/linelist/rovibrational: zero matches across recipes, registry, ledger, downstream families and the downstream registry. No molecular spectroscopy or energy-level material exists at any width.
- Homogeneity: Single quantity and unit (state energy term value, cm^-1) in a single standardized ExoMol format and generation process (variational line-list calculations, partly MARVEL-substituted). One dataset per molecule avoids near-duplicate isotopologue copies. Level density and energy range differ across molecules but stay within one unit and one representation (6-decimal lattice).
- Risks: Text-to-float64 parse; this is justified by 11-12 significant digits (beyond float32) and follows the noaa_cors_rinex text-to-f64 precedent. A judge may question cross-molecule homogeneity, so keep the strictly one-dataset-per-molecule rule. The CC BY-SA share-alike condition has repo precedent (asterisk_core_sounds_ulaw_u8, zenodo_crab_giant_pulse_sigmf_ci16). A few datasets declare 0 states or are huge (H2CS 52M, C2H4 45M), so cap by the .def state count. File order is J/symmetry-block sorted (sawtooth).
- Probe evidence: exomol.all fetched (189 KB; 102 molecules, 242 isotopologues, 250 datasets). All 250 .def files fetched (about 0.5 MB total); state counts were tallied for 234 datasets (387M total; 206 datasets at or under 5M states). HEAD on AlCl YNAT and H2O POKAZATEL .states.bz2 returned 200 (965,018 and 12,667,256 bytes). A 450 KB prefix of the AlCl .states.bz2, decompressed, shows lines such as '3488 29170.834712 552 11 4.632000 1.0382E+00 + f a(3PI) ...', confirming the f12.6 energy column.

Proposed by the autocollect scout on 2026-10-05 (transcript `.data/pipeline/logs/scout_64bit/scout.20261005_215706.jsonl`).
