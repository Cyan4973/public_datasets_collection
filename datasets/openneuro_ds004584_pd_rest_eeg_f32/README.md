# OpenNeuro ds004584 Resting-State 63-Channel Scalp EEG Float32

Thirty whole eyes-open resting-state scalp EEG recordings from OpenNeuro
`ds004584` ("Rest eyes open", University of Iowa Narayanan lab, BIDS 1.2.1,
DOI `10.18112/openneuro.ds004584.v1.0.0`). Each recording is the EEGLAB
`.fdt` voltage matrix as distributed: 63 channels × 60k–124k time points of
little-endian IEEE float32 at 500 Hz. One recording is one sample.

## Source and license

- `dataset_description.json` declares `"License": "CC0"`. `download.sh`
  checks this field, the DOI and the dataset name before fetching anything
  else.
- Objects come from the public anonymous bucket
  `https://s3.amazonaws.com/openneuro.org/ds004584/`. `CHANGES` lists only
  version 1.0.0 (2023-05-31).

## Selection

The release has 149 subjects (README: 100 Parkinson's disease, 49 controls)
and four channel layouts in `channels.tsv`:

| subjects | channels | difference from canonical |
|---:|---:|---|
| 109 | 63 | canonical montage (`canonical_channels.txt`) |
| 29 | 64 | adds `Resp` (respiration, not EEG) |
| 10 | 63 | `FT9`/`PO3`/`PO4` in place of `Iz`/`I1`/`I2` |
| 1 | 66 | adds `X`/`Y`/`Z` |

Only the 109 canonical-montage subjects are eligible, so every sample has the
same channels in the same order. From the sorted eligible ids, 30 are taken
at evenly spaced positions `round(i*108/29)`, `i = 0..29` (sub-009 to
sub-139). This spreads the selection over the id range rather than taking a
contiguous block. `selection.tsv` pins each `.fdt` and both sidecars by size
and MD5 (S3 single-part ETag). `discover.sh` reproduces the selection from the
listing and sidecars alone and never fetches signal data.

Selected scope: 30 recordings, 605,908,800 bytes, 151,477,200 values. Median
recording: 76,475 points (about 153 s), 4.82M values, 19.3 MB. Range:
120.9–248.2 s.

## Decode

EEGLAB writes `EEG.data` (`[nbchan × pnts]`, MATLAB column-major) as raw
float32, so the channel index varies fastest: element `t*63 + c` is channel
`c` at time `t`. `nbchan` is the number of `channels.tsv` rows. It must equal
`EEGChannelCount` in `*_eeg.json`, the `.fdt` size must be divisible by
`4*nbchan`, and `size / (4*nbchan)` must equal `RecordingDuration × 500`.
The `.set` MATLAB files are never fetched or parsed.

Output samples hold the same values in the same order (a C-order
`[pnts, 63]` float32 matrix):
`samples/openneuro_ds004584_pd_rest_eeg_f32/ds004584_rest_eeg_63ch_f32/sub-XXX_task-Rest_eeg_63ch_f32le.bin`.

## As distributed

The preprocessing history is not documented. `SoftwareFilters` is `n/a`, and
the values do not lie on any ADC lattice (0.1, 0.0488, 0.01, 0.5 and 1/2048 µV
lattice hit rates match the ~4% random baseline) and use the full float32
mantissa. Whole-recording channel means are near zero while slow baseline
drift remains, which suggests undocumented mean removal or low-cutoff
high-pass filtering upstream. The data are not average-referenced. The sidecar
unit is `n/a`; microvolts is the EEGLAB convention and fits the observed
magnitudes. Artifacts are not clipped or removed: several recordings have
mV-scale excursions (sub-043 reaches −9.4 mV, sub-009 +5.2 mV). NaN/Inf fails
the build.

## Sensitive-data note

This is a clinical cohort. The recipe keeps only de-identified voltage
matrices and the channel and acquisition sidecars needed to decode them. It
never downloads or emits `participants.tsv`, `participants.json`, `.set`
metadata, group labels, demographics or clinical scores, and `verify.sh`
fails if any such file appears in the download directory.

## Run

```bash
bash staging/openneuro_ds004584_pd_rest_eeg_f32/download.sh   # ~606 MB
bash staging/openneuro_ds004584_pd_rest_eeg_f32/build.sh
bash staging/openneuro_ds004584_pd_rest_eeg_f32/verify.sh
```
