# PhysioNet CirCor DigiScope pediatric phonocardiograms (int16)

This recipe collects every public heart-sound recording in release 1.0.3 of
the CirCor DigiScope Phonocardiogram Dataset on PhysioNet. That is 3,163
auscultation recordings from 942 pediatric patients, recorded in two cardiac
screening campaigns in Pernambuco, Brazil, with a Littmann 3200 electronic
stethoscope (DigiScope Collector). Each recording becomes one sample: the
recording's complete mono 4000 Hz signed 16-bit PCM stream, stored as raw
little-endian int16.

The recipe takes the full public population (about 579 MB of output). It does
not subset.

## Material

- Quantity: chest-wall acoustic amplitude (phonocardiogram), stored as native
  16-bit PCM codes. There is no gain scaling, filtering or resampling.
- Sites: aortic `AV` (800), pulmonary `PV` (766), tricuspid `TV` (732),
  mitral `MV` (861), and the rare other position `Phc` (4). The 43 repeat
  recordings at a site (`_1`, `_2`, `_3` suffixes) are separate samples.
- Lengths: 20,608 to 258,048 values per recording (about 5 to 65 s). The
  median is about 85,800 values (21 s).
- Not emitted: demographics, murmur and outcome labels (`training_data.csv`
  and the per-patient `.txt` files), and the `.tsv` heart-cycle
  segmentations. These are not even downloaded.

All recordings come from one study, one device type, one sampling rate and
one bit depth. They measure one quantity, at different chest positions. The
recipe does not mix in other heart-sound sets such as PhysioNet/CinC 2016 or
EPHNOGRAM, which use other devices and rates.

## Novelty

This is new content in a known modality. The local corpus already has PCM16
audio (`esc50_environmental_audio_i16`, `librispeech_dev_clean_i16`,
`nsynth_test_notes_i16`, `openslr_rirs_noises_pcm16`, the NOAA passive-acoustic
recipes) and PhysioNet physiological waveforms (`physionet_bidmc_ppg_resp_i16`,
the MIT-BIH ECG recipes). No recipe, registry row, ledger row or downstream
family contains phonocardiograms. The material is distinct from both
neighbours:

- unlike airborne audio, it is low-band cardiac acoustics picked up through a
  stethoscope chest piece at 4 kHz;
- unlike the other PhysioNet waveforms, it is acoustic rather than
  electrical or optical.

## Source and rights

- Source: the anonymous PhysioNet open-data bucket,
  `https://physionet-open.s3.amazonaws.com/circor-heart-sound/1.0.3/`. This
  is a mirror of `physionet.org/files/circor-heart-sound/1.0.3/`. The
  version is pinned.
- License: the ODC Attribution License 1.0. The release's own `LICENSE.txt`
  (sha256 `86c0ad30…`) is listed in the release `SHA256SUMS.txt`, and
  `download.sh` pins and re-checks it. This is the same license and access
  class (open access, no credentialing) as the accepted
  `physionet_bidmc_ppg_resp_i16` recipe.
- Attribution: Oliveira et al. 2022, "The CirCor DigiScope Dataset: From
  Murmur Detection to Murmur Classification", IEEE JBHI 26(6):2524-2535,
  doi:10.1109/JBHI.2021.3137048. Also cite the PhysioNet dataset page and
  Goldberger et al. 2000 (PhysioNet).
- Safety: the recordings are de-identified human health data. Only the PCM
  waveform is emitted. Recordings can contain incidental body or ambient
  sound, as any stethoscope audio can.

## Running

Run from the repository root:

```bash
bash staging/physionet_circor_pcg_i16/download.sh   # ~580 MB, 6,329 small GETs
bash staging/physionet_circor_pcg_i16/build.sh
bash staging/physionet_circor_pcg_i16/verify.sh
```

### `download.sh`

1. Fetches `SHA256SUMS.txt`, `LICENSE.txt` and `RECORDS`, each pinned by
   SHA-256.
2. Fetches every `<record>.wav` and `<record>.hea` named in `RECORDS`, in
   passes:
   - each pass runs one parallel curl (8 connections, `--retry 10`, no
     per-file `--max-time`; stalls are caught by `--speed-limit` and
     `--speed-time`);
   - each file lands as a `.part`, and is promoted only when its SHA-256
     matches `SHA256SUMS.txt`;
   - corrupt files are deleted and refetched on the next pass.
3. Validates every WAV/header pair semantically and pins the aggregate
   sizes: 578,849,274 B of WAV and 187,976 B of headers.

### `build.sh`

Uses only local files. For each record:

1. Re-checks both checksums.
2. Walks the RIFF chunk list to find `fmt ` and `data`, without assuming a
   fixed 44-byte header.
3. Requires PCM tag 1, 1 channel, 4000 Hz, 16 bits, byte rate 8000 and block
   align 2.
4. Cross-checks against the WFDB header:
   - data length = 2 × the header's sample count;
   - data offset = the header's `16+<offset>`;
   - header site label = the site in the filename.
5. Writes the int16 values.

Recordings with fewer than 16 distinct codes, or whose payload is
byte-identical to an earlier recording, are excluded and listed in
`filtered/<id>/ingest_stats.json`. More than 1% exclusions fails the build.

### `verify.sh`

Re-decodes every source WAV independently with the stdlib `wave` module and
parses each header with a separate tokenizer. It then checks:

- every sample's bytes against the re-decoded payload;
- every index field;
- that the exclusion set matches the re-derived rule;
- that there are no stray files;
- the aggregate output SHA-256;
- the manifest totals.

It rejects constant or degenerate samples and reports the full-scale
(clipping) fraction.

Both `build.sh` and `verify.sh` first self-test the decoders on synthetic
WAVs. The synthetic inputs include an extra odd-length chunk and nine invalid
variants.

## Outputs

- Samples: `.data/samples/physionet_circor_pcg_i16/circor_pcg_pcm_i16/<patient>_<site>[_<n>].bin`
- Index: `.data/index/physionet_circor_pcg_i16/samples.jsonl`. Each row
  carries the standard fields plus the recording ID, site, min/max, distinct
  count, full-scale count and SHA-256.
- Stats: `.data/filtered/physionet_circor_pcg_i16/ingest_stats.json`
- Logs: `.data/logs/physionet_circor_pcg_i16/`

## Realized scope

Figures from the build and verify of 2026-10-05:

- Download: 6,326 recording files fetched in a single pass, all matching
  `SHA256SUMS.txt`. 580.6 MB in total under `.data/*/physionet_circor_pcg_i16`
  at download time.
- Output: 3,163 samples from 942 patients, with 0 exclusions.
  - Sites: AV 800, PV 766, TV 732, MV 861, Phc 4.
  - 289,355,051 int16 values in 578,710,102 bytes.
  - Median sample: 85,824 values. Range: 20,608 to 258,048.
  - Aggregate output SHA-256:
    `42342b450a0e91f6442f2105ac0379ed4d47e2de97ab9886588f14a6be82a017`.
- Content: every recording is rich, with 1,767 to 47,152 distinct codes
  (median 6,545). Codes near zero are dense, with no scaling lattice. A
  typical recording has median |x| of a few hundred and p99 |x| of a few
  thousand. The minimum peak-to-peak is 5,326 codes.
- Clipping: 83,638 values sit exactly at full scale (-32768 or 32767), a
  fraction of 0.029%.
  - 1,970 recordings touch full scale at least once. In 1,531 of them, both
    rails are reached.
  - Per recording, the median clipped fraction is 0.003% and the 99th
    percentile is 0.59%. Only 17 recordings exceed 1%; the maximum is 4.35%.
  - The output is not peak-normalized: 1,193 recordings never reach full
    scale, and the 5th percentile of max |x| is 25,605.
  - These are sparse transient saturations of the device output, most likely
    from stethoscope contact or motion. They are kept as recorded and
    reported, not masked.
