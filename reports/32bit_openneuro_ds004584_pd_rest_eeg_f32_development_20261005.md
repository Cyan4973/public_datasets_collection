# OpenNeuro ds004584 resting-state scalp EEG float32 development

## Outcome

Accepted `openneuro_ds004584_pd_rest_eeg_f32`: 30 whole eyes-open resting-state scalp EEG recordings from OpenNeuro `ds004584` v1.0.0 ("Rest eyes open", University of Iowa Narayanan lab). Each is emitted as the distributed EEGLAB `.fdt` little-endian float32 voltage matrix.

- This is the first EEG family at 32 bits. Local and downstream EEG is otherwise only 16-bit PhysioNet EDF integer codes (`eeg_physionet`, `chbmit_physionet`, downstream `eeg_c3`/`eeg_c4`/`eeg_cz`).
- It is also the first native-float scalp EEG.
- Novelty kind: `new_source`. Scalp EEG already exists at another width, so it is not a new modality.

## Source and rights

- Source: public anonymous S3 bucket `https://s3.amazonaws.com/openneuro.org/ds004584/`.
- Release: BIDS 1.2.1, 1,051 keys, 149 `*_task-Rest_eeg.fdt` objects totalling 3,020,968,040 B. `CHANGES` lists only 1.0.0 (2023-05-31).
- License: CC0. The release's own `dataset_description.json` (MD5 `e638be12229b176a735782d36c850dfb`) declares `"License": "CC0"` and `"DatasetDOI": "doi:10.18112/openneuro.ds004584.v1.0.0"`. `download.sh` refuses to fetch signal data unless License, DOI and Name all match. The dataset README adds no other terms.
- Safety: the cohort is clinical (100 Parkinson's disease, 49 controls). The recipe fetches only the `.fdt` matrices plus `channels.tsv`/`eeg.json` sidecars. `participants.tsv`, `.set` metadata, group labels and demographics are never downloaded or emitted, and `verify.sh` fails if they appear. `contains_sensitive_data = true`, `contains_personal_data = false`, matching the accepted OpenNeuro ds000030 and TCIA precedents.

## Shape and conversion

The upstream release has four montages:

| Recordings | Montage | Status |
|---:|---|---|
| 109 | canonical 63 channels | kept |
| 29 | 64 channels, adds `Resp` (respiration) | excluded |
| 10 | 63 channels, `FT9`/`PO3`/`PO4` in place of `Iz`/`I1`/`I2` | excluded |
| 1 | 66 channels, adds `X`/`Y`/`Z` | excluded |

Excluding the last three groups means every sample has the same channels in the same order.

Selection:
- 30 recordings are taken at evenly spaced positions `round(i*108/29)` over the sorted eligible ids, sub-009 to sub-139.
- Each `.fdt` and both sidecars are pinned by size and MD5 in `selection.tsv`.
- `discover.sh` regenerates the selection from the listing and sidecars alone.

Decode and checks:
- EEGLAB writes `EEG.data` [nbchan × pnts] column-major, so element `t*63 + c` is channel `c` at time `t`.
- `nbchan` comes from the `channels.tsv` rows and must equal `EEGChannelCount`.
- The file size must divide by 252, and `size/252` must equal `RecordingDuration × 500`.
- Samples are byte-identical to the sources: no clipping, filtering, re-referencing or rescaling. NaN or Inf fails the recipe.

Preprocessing before export is undocumented (`SoftwareFilters` is `n/a`):
- Whole-recording channel means are near zero while slow baseline drift remains.
- The values sit on no ADC lattice.
- Judge forensics (below) show that same-channel *differences* partly keep the 0.048828125 µV actiCHamp step. That is consistent with slow-drift removal applied to recordings from a single acquisition resolution. The stored values are therefore genuine floats, not widened integer codes.

## Accepted output

| Measure | Value |
|---|---|
| Primary series | `ds004584_rest_eeg_63ch_f32` (float32 LE, [pnts, 63]) |
| Samples | 30 (one subject recording each) |
| Primary values | 151,477,200 |
| Primary bytes | 605,908,800 |
| Sample size range | 3,809,610 to 7,817,040 values (60,470 to 124,080 points; 120.9 to 248.2 s) |
| Median sample | 4,817,925 values (76,475 points, 153.0 s) |
| Global min / max | −9426.38 µV (sub-043) / 5242.30 µV (sub-009) |
| Median per-recording min / max | −378.3 / 502.6 µV |
| Recordings with >1 mV excursions | 8 of 30 (kept unclipped) |
| Flat channels | 0 |
| Distinct sample SHA-256s | 30 of 30 |

Aggregate SHA-256 of the samples concatenated in index order: `e0cdc77e788f59a8be8dee97d1e6460f47fafd3129022ecbecd1e7538104965e`.

## Judge checks

- **Gate:** `python3 tools/autocollect/gate.py staging/openneuro_ds004584_pd_rest_eeg_f32` passed with no warnings.
- **Verify:** my own `bash verify.sh` run passed (30 samples, 151,477,200 values, 605,908,800 B). The verifier does not import the builder. It re-hashes sources, re-parses sidecars, checks byte identity, checks finiteness by float64 sum, recomputes stored min/max and flat channels, and reconciles index and manifest totals.
- **Local files only:** `build.sh`, `ds004584_eeg.py` and `verify_ds004584.py` contain no network calls. No credentials appear anywhere in the recipe.
- **Selection reproduced:** `discover.sh`, run into `/tmp`:
  - the listing has 1,051 keys and 149 `.fdt` objects totalling 3,020,968,040 B
  - sidecar fetches were 1.2 MB
  - the census is 109/10/29/1
  - the regenerated `selection.tsv` is identical to the pinned one
- **Bytes, all 30 samples (stdlib `array`):**
  - Layout: same-channel lag-63 mean |Δ| is 2.0–8.7 µV against 6.5–226 µV for adjacent-channel lag-1, confirming channel-fastest interleaving.
  - Values: median |x| is 6.5–55 µV. There are no exact zeros and no duplicated channel columns. The distinct ratio is 0.997–0.999, and the low mantissa byte takes all 256 values.
  - Distinctness: the first-500-point MD5s are 30/30 distinct. Pairwise exact-value overlap in mid-recording windows is at most 613 of ~126k values (median 186), i.e. chance; there are no near-duplicate recordings.
  - Lattice forensics: values hit the 0.1, 0.0488, 0.01 and 0.5 µV lattices at the ~4% random baseline. Same-channel differences reach 0.89–1.00 hit rates at 0.048828125 µV on some channels and 0% on others, with harmonics at 0.0244 and 0.0977 µV. 0.1, 0.5 and 0.01 µV stay at baseline in every recording, so there is one acquisition resolution and one processing path across the family. The manifest's "no ADC lattice" statement is accurate for values but does not mention this difference-domain structure.
  - Artifacts: sub-009 has ~3% of values above 1 mV across many channels, and sub-105 and sub-028 have similar multi-channel mV bursts. These come from the same process, are kept as distributed, and are documented.
- **Rights:** the live `dataset_description.json` was re-fetched, its MD5 matches the pin, and it says CC0. The live `README` and `CHANGES` add no other terms. The `eeg.json` sidecars contain only acquisition fields and the institution address.
- **Novelty:**
  - `novelty.py --url https://s3.amazonaws.com/openneuro.org/ds004584/ --terms ds004584 EEGLAB fdt 'resting EEG' 'eyes open' Parkinson eeg` matched only the candidate itself on path and terms.
  - `eeg` hits only 16-bit recipes and downstream families, and the registry has no hit.
  - Labelled `new_source`, not `new_modality`, because scalp EEG exists locally at 16 bits.
- **Volume:**
  - 30 samples is above the ~20 'acceptable' guidance.
  - The eligible population is 109 recordings (~2.18 GB), so it is cap-bound.
  - 606 MB is ~6× the ~100 MB downstream need, and the download size equals the kept size.
  - The selection's PD/control balance is unknown: the recipe deliberately never reads group labels.
