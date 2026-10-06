# DANDI:000020 Patch-seq current-clamp membrane potential (float32)

This recipe collects complete whole-cell current-clamp sweeps from the Allen Institute's
Patch-seq recordings of mouse visual-cortex neurons, mostly GABAergic interneurons. The
source is the published DANDI dandiset 000020, version 0.210913.1639. Each sample is one
CurrentClampSeries sweep: the neuron's membrane potential in mV at 50 kHz while a current
stimulus ran (test pulse, long and short squares, ramps, chirp/noise, rheobase search).
Values are the archive's own float32 words, emitted unchanged.

- License: CC-BY-4.0. The published `dandiset.yaml` contains `license: - spdx:CC-BY-4.0`
  and `access: - status: dandi:OpenAccess`, and every asset in `assets.yaml` is
  `dandi:OpenAccess`. Cite: Allen Institute for Brain Science (2021) Patch-seq recordings
  from mouse visual cortex (Version 0.210913.1639). DANDI archive.
  https://doi.org/10.48324/dandi.000020/0.210913.1639
- Access: anonymous S3 (`dandiarchive.s3.amazonaws.com`), no credentials.

## Scope and selection

The release holds 4,435 NWB files from 1,040 donors (141.9 GB). One file is one neuron.
The recipe takes a bounded, deterministic subset (`scripts/patchseq_cc.py derive_selection`):

1. Sort donors by numeric id and keep ids >= 732,239,848. This is the gain-0.05 window
   found by the survey below: 522 donors.
2. Take 16 donors at evenly spaced ranks `round(i * 521 / 15)`, so the subset spans the
   whole window, from its first donor to the newest 10-digit ids.
3. Per donor, take the lexicographically first NWB path.

The result is pinned in `sources.tsv`: 16 files, 521,558,599 bytes, each with its
`dandi:sha2-256`. `download.sh` re-derives the selection from the pinned `assets.yaml`
(SHA-256 `65ef568e…`) and requires a byte-identical match.

## Why one gain regime (homogeneity)

Every value is a 16-bit ITC-18 ADC code divided by the amplifier gain, as MIES writes it
into float32. The release mixes two gain settings, which give two different float32
regimes:

| gain (`CurrentClampSeries/gain`) | value step (tick lattice) | donors (probed) |
|---|---|---|
| 0.01 | 1/32 mV (dyadic) | ids <= 703,285,815 |
| 0.05 | 1/160 mV = 0.00625 mV (non-dyadic) | ids >= 732,239,848 |

The restriction to gain 0.05 is purely about homogeneity: mixing the two settings would put
two tick lattices with different scales in one family. The build requires gain ==
float32(0.05) for each sweep. Any other gain is excluded and counted. The build and verify
then check every emitted word exactly against the lattice rule (see Width honesty).

### Gain regime survey (2026-10-05, `probe_gain_regime.py`, range reads only)

Probed donors (first NWB of each) and their CurrentClampSeries gains:
645665052, 657610063, 679293588 and 703285815 were all 0.01, and so was 639391596
(downloaded whole). 732239848, 740369784, 746220175, 750787701, 757080785, 782818178,
825548714, 868713258, 948346189, 992435487 and 1001658946 were all 0.05. No probed cell
mixed gains. The 119 donors between 703,285,815 and 732,239,848 were not probed and are
outside the window.

## Decode path

The decoder is pure-stdlib (`scripts/nwb_hdf5.py`). It reads HDF5 superblock v0, v1
object headers with continuations, and old-style symbol-table groups (v1 group B-tree,
local heap, SNOD; soft links recorded but never followed). Attributes are read with
variable-length strings resolved from global-heap collections. Datasets use layout v3
(chunked, contiguous or compact) and filter pipeline v1/v2.

The sweep `data` is chunked at 8192 float32 values with filters [shuffle(4), deflate]. Each
chunk is `zlib.decompress`ed and byte-unshuffled, edge padding is dropped, and the
little-endian float32 words are emitted bit-exact. The reader never dereferences the
undefined address `0xffffffffffffffff`.

Sweeps are chosen by the group attribute `neurodata_type == "CurrentClampSeries"`, never by
name. VoltageClampSeries (pA) and `/stimulus` command waveforms are excluded. Each emitted
sweep must also have `data@unit == "volts"`, `data@conversion == float32(0.001)` (stored
numbers are mV), `starting_time@rate == 50000` and gain 0.05.

Every emitted word must equal `float32(k / (3200 * g))` for an integer ADC code `k`. Here
3200 is ITC-18 codes per volt, `g` is the stored float32 gain 0.05000000074505806, and the
division is done in double precision. The build checks this for all values, as does
verify, which repacks bit for bit. Any mismatch fails the recipe.

Self-test: a synthetic HDF5 v0 file written by an independent writer covers vlen-string
attributes in the global heap, a continuation block, a soft link, multiple SNODs, a
two-level chunk B-tree, a chunk with the deflate filter masked off, and partial edge
chunks. The decoder reproduces every array byte-exactly and makes the expected emit or
exclude decision for each sweep type: VC, wrong gain, wrong rate, trailing-zero trim,
too short after trim, constant, interior NaN, and an X7Ramp sweep with one allowed interior
fill run. The fill policy rejects interior fill in a non-ramp sweep, two runs in one sweep,
and fill above 2%. Verify's independent re-check rejects fill missing from the index, fill
under the wrong stimulus, and a word moved one ulp off the lattice. A real file
(sub-639391596, gain 0.01, run with the regime constants patched for the test) built and
verified end-to-end. Its 15 CC sweeps stored 4.42M values, of which 2.60M were emitted
after tail trimming.

## Missing values

MIES writes exact zeros for spans it did not acquire. This happens in two places.

**Trailing fill (trimmed).** When MIES ends a sweep early, for example a rheobase or blip
search that stops after spiking, it pads the rest of the stored array with exact zeros, or
NaN in some versions. The recipe trims the maximal trailing run of +0.0/-0.0/NaN words as
unacquired and records `stored_values` and `trimmed_tail_values` per sample in the index.
Measured: 271 sweeps, 59,029,871 of 171,305,500 stored values, all +0.0.

**Interior fill (kept as stored, flagged).** In 44 of the 73 X7Ramp sweeps (14 donors,
84,460,956 bytes), the ramp's spike train is followed by one interior run of exact 0.0 words.
These runs are 960 to 1,983 values long (19–40 ms), 62,033 values in total, before the trace
resumes. For example, in sub-732239848 data_00033 at index 271,990 the trace reads
-37.075 mV, then 1,005 zeros, then -61.694 mV. This is MIES's spike-triggered DAQ stop and
restart. These zeros are not membrane potential: they are the same unacquired fill that is
trimmed at the tail.

The sweeps are kept whole because they are the natural records, and are not split at the
gap. Each index row lists `interior_fill_runs` ([[start, length], ...], counting runs of at
least 50 consecutive ±0.0 words) and `interior_fill_values`. `ingest_stats.json` carries the
totals, and the counts of 44 samples and 62,033 values are pinned. Build and verify
enforce the observed pattern and fail on anything new: fill only in X7Ramp sweeps, at most
one run per sweep, at most 2% of a sweep. The largest observed fraction is 0.91%. Verify
recounts the runs straight from the sample bytes. Exact zeros outside such runs are genuine
ADC code 0: there are only 36 of them, each isolated, at spike crossings of 0 mV.

Sweeps are excluded and counted when they have interior NaN/Inf, fewer than 1,000 values
after trimming, or a constant value. Nothing is imputed.

## Width honesty

Measured over all 112,275,629 emitted words:

- **Exact lattice.** Each word equals `float32(k / (3200 * g))` for an integer ADC code `k`
  in [-16,768, 8,549], with `g` = float32(0.05) and the division done in double precision.
  The effective divisor is therefore 160.0000024, not exactly 160. About 80% of words
  equal the correctly rounded float32(k/160). The remaining 22,449,239 words sit one ulp
  toward zero from that value.
- **Deterministic low bits.** The low mantissa bits follow the periodic binary expansion
  of 1/5. The low byte takes only 5 distinct values (0, 51, 102, 153, 205, each about 20%),
  and 14.4% of words have their low 13 mantissa bits zero.
- **Information content.** Each word carries at most about 15 bits of ADC information:
  the code span is 25,318 codes, about 14.6 bits.

float32 is kept because it is the archive's native stored type. MIES writes the scaled
float32 words and the integer codes are not stored, so recovering them would be a local
remap, which protocol rule 2 forbids. This is the same reasoning as the accepted
`kollmeyer_panasonic18650pf_drive_cycle_voltage_f64` precedent: producer-native floats on
an ADC lattice. The family is a 16-bit-information signal in its producer's float32
container, and should be weighed as such.

## Novelty

There is no intracellular electrophysiology or patch-clamp material in the local recipes,
the registry, the pipeline ledger, or the downstream corpus (novelty.py, 2026-10-05).

- **Nearest DANDI and 32-bit neighbour:** `dandi_001076_zebrafish_calcium_fluorescence_f32`,
  accepted 2026-10-05. It holds DANDI:001076 two-photon Suite2p ROI fluorescence in float32:
  optical calcium-indicator brightness per imaging frame, about 0.9 Hz, continuous float values.
  This family is intracellular electrical membrane potential at 50 kHz on a 16-bit ADC
  lattice, with action potentials and stimulus-locked current-clamp responses. Both come
  from DANDI, but they are different instruments, quantities and value structures.
- **Nearest electrophysiology families:** `openneuro_ds004584_pd_rest_eeg_f32` (scalp EEG
  voltage, 500 Hz, float32), `openneuro_ds004212_things_meg_ctf_i32` (MEG SQUID ADC counts,
  int32), `zenodo_open_ephys_continuous_i16` (30 kHz extracellular tetrode voltage, int16) and
  `zenodo_npx_opto_templates_f32` (Kilosort spike templates). All of these are extracellular
  or non-invasive recordings.

## Commands

```bash
bash staging/dandi_000020_patchseq_current_clamp_f32/download.sh   # 532,737,831 bytes
bash staging/dandi_000020_patchseq_current_clamp_f32/build.sh
bash staging/dandi_000020_patchseq_current_clamp_f32/verify.sh
```

Outputs:

- `samples/<id>/patchseq_cc_membrane_potential_f32/sub-<donor>_ses-<session>__data_<sweep>_AD0.bin`
- `index/<id>/samples.jsonl`
- `filtered/<id>/ingest_stats.json`, with per-file emitted and excluded counts by reason.

## Realized output

First build, 2026-10-05:

- 736 samples from 16 donors (16 neurons). Every selected file contributed, with 33 to 105
  sweeps per neuron.
- 112,275,629 float32 values, 449,102,516 bytes. The 700 MB running cap and the 1 GB hard
  cap were not reached.
- Sample length: minimum 7,650 values (complete 153 ms short-pulse search sweeps), median
  54,650, maximum 1,180,000 (23.6 s chirp sweeps). All sweeps are 50 kHz.
- Value range -104.80 to +53.43 mV. ADC codes run from -16,768 to 8,549, and every word
  passes the exact lattice rule.
- Distinct values per sample, counted over full samples: 174 (an X2LP_Search sweep) to
  11,816 (a C2NSD noise sweep). Capped at the first 65,536 values the range is 174–6,807.
- Interior fill: 44 X7Ramp sweeps from 14 donors, one run each of 960–1,983 zeros,
  62,033 values in total and at most 0.91% of any sweep. Kept and flagged in the index.
  There are also 36 isolated genuine zero values.
- Acquisition series: 736 CurrentClampSeries were emitted and 289 VoltageClampSeries
  excluded. No CurrentClampSeries was excluded for gain, rate, unit, length, constancy or
  NaN.
- Tail trimming: 271 sweeps ended in exact +0.0 runs, with no NaN tails. The runs were
  213 to about 1.5M values long, median 142,059. In total 59,029,871 of 171,305,500 stored
  values were removed.
- Stimulus mix: 201 X5SP_Search, 100 X2LP_Search, 86 X1PS_SubThresh, 73 X7Ramp,
  71 X4PS_SupraThresh, 55 X3LP_Rheo, 55 X6SP_Rheo, 44 C2SSTRIPLE, 25 C1SQCAPCHK, 11 C2CHIRP,
  15 C2NSD noise.
- Aggregate SHA-256 over all samples in index order:
  `c0e5fda2f6674ec41a987907331a9b32ec5466264b36b37ce9cf1ca822be1515`. build and verify
  check it, together with the pinned sample count and byte total.
