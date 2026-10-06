# PhysioNet TPEHG DB unfiltered electrohysterogram int16 development

## Outcome

Accepted `physionet_tpehg_ehg_i16` from the pinned PhysioNet Term-Preterm EHG
Database v1.0.1 (TPEHG DB, DOI 10.13026/C2FW2V).

The family is uterine smooth-muscle EMG (electrohysterogram), recorded with
abdominal surface electrodes at 20 Hz. No layer of the corpus has it. The
nearest existing families are EEG (`chbmit_physionet`, `eeg_physionet`), ECG
(`mitbih_arrhythmia_physionet`), PPG/respiration
(`physionet_bidmc_ppg_resp_i16`), phonocardiogram (`physionet_circor_pcg_i16`)
and skeletal forearm sEMG (`uci_emg_gestures_i8`). It is labelled a new
quantity within the known biopotential-waveform modality, not a new modality.

The release contains two ADC code lattices, and they line up exactly with the
header sampling-frequency string. The recipe therefore emits two homogeneous
primary series of the same quantity rather than one mixed series.

## Source and rights

- Source: PhysioNet open-data S3 mirror
  `https://physionet-open.s3.amazonaws.com/tpehgdb/1.0.1/`. The project page
  itself advertises this mirror.
- Pinned `SHA256SUMS.txt` sha256:
  `6da37c0d996bf7706964f291282861449ccb84005500a1c16aefda3d8fcdbf3e`
  (606 entries). It transitively pins `RECORDS` and all 300 `.hea`/`.dat`
  pairs.
- Download: 256,267,521 B total; 255,741,624 B of `.dat` and 302,194 B of
  `.hea`.
- License: Open Data Commons Attribution License v1.0 (ODC-By-1.0).

The project page states "Access Policy: Anyone can access the files, as long
as they conform to the terms of the specified license. License: Open Data
Commons Attribution License v1.0". Its JSON-LD metadata gives the license as
`https://opendatacommons.org/licenses/by/index.html`. download.sh saves the
page and fails if either statement disappears. Attribution to Fele-Zorz et
al. 2008, the dataset DOI and PhysioNet is carried in the manifest.

The recordings are de-identified. Header comment lines hold clinical fields
(gestation, age, parity and others); none of them is emitted, and
`tpehgdb.smr` and the `.fvl` feature files are not downloaded.

## Shape and conversion

Each `.dat` holds 12 frame-interleaved WFDB format-16 signals. Signals `1`,
`2` and `3` (indices 0, 4, 8) are the database's unfiltered bipolar channels:

- S1 = E2 − E1
- S2 = E2 − E3
- S3 = E4 − E3

The other nine signals are offline 4-pole Butterworth band-pass derivatives
(DOCFILT) and are excluded.

One sample is one complete channel of one recording, written unchanged as
little-endian int16. No rescaling, clipping or imputation is applied.

Records are routed by the header frequency string, and both build and verify
assert the lattice on every channel:

- `20.000000` → `tpehg_ehg_unfiltered_adc_step1_i16`. All 16 residues mod 16
  occur, and the two most common hold 0.127–0.157 of the values.
- `20.000110` → `tpehg_ehg_unfiltered_adc_step16_i16`. Every value lies on two
  adjacent residues mod 16.

Corrections to the builder's characterization, verified by the judge:

- **Mean-removed channels.** 893 of 900 channels have |mean| < 1, so the
  source stored per-channel mean-removed signals. The values are stored WFDB
  codes of the unfiltered channels, not strictly raw ADC output.
- **Origin of the step16 lattice.** The per-channel lattice phase, which
  covers all 16 residue pairs, and the one-residue flip at the sign boundary
  fit a source-side rescale of roughly 12-bit codes by about 16 followed by
  mean removal.
- **Wrap-around, not real excursions.** The near-rail values in about 10
  step1 channels (e.g. tpehg725, tpehg800, tpehg1167) are int16 wrap-around in
  the source's stored codes; for example, 32693 → −32722 while the DOCFILT
  copies stay smooth. They sit in onset transients within the first ~2,100
  frames and are preserved as published.
- **Constant plateau.** tpehg1241 ch3 opens with a constant run of 1,133
  values.

## Accepted output

| series | records | samples | values | bytes | min / median / max values |
| --- | ---: | ---: | ---: | ---: | --- |
| `tpehg_ehg_unfiltered_adc_step1_i16` | 174 | 522 | 18,356,100 | 36,712,200 | 15,060 / 35,280 / 35,460 |
| `tpehg_ehg_unfiltered_adc_step16_i16` | 126 | 378 | 13,611,603 | 27,223,206 | 31,305 / 36,000 / 39,873 |
| total | 300 | 900 | 31,967,703 | 63,935,406 | median 35,350 |

- Step1 code range: −32,745..32,734. Distinct values per channel: 703–13,122.
- Step16 code range: −24,276..22,028. Distinct values per channel: 50–1,223.
- Saturation codes −32768 / +32767: none.
- Aggregate SHA-256 of concatenated samples in index order:
  - step1 `6f07c83bc6ce0443221cb36c6f90db5998be20491407660a8940ba7b9ff07726`
  - step16 `0be9e0da186e1928ffbda132ce8dc510c235f6498922074cb4f22f87eba4ca25`

## Judge checks

- `gate.py`: PASS with no warnings (values 31,967,703; bytes 63,935,406;
  samples 900; median 35,350; widths [16]).
- `verify.sh` (run by the judge): ok. It independently parses the headers,
  decodes with `struct`, re-checks all 12 WFDB checksums per record, compares
  every sample byte and index field, and checks the manifest's per-series
  counts and sizes.
- Download reproducibility: the current `download.sh` sha256 `b975aceb…45ef`
  equals the driver-recorded `download_sha`. Build and verify make no network
  calls.
- Independent decode: 6 random samples (3 per series) match the source
  stride-12 extraction byte-for-byte, and the header checksums agree.
- Lattices: step1 has dominant unit gaps, a near-uniform low nibble (share
  0.058–0.067) and about 50% parity. Step16 has diffs in multiples of 16 and
  per-channel residue pairs spanning all 16 phases.
- Scale coherence: median IQR is 623 (step1) vs 495 (step16) codes, the
  log2-IQR histograms overlap, and step1 shows no gain sub-cluster.
- Duplicates: a content-anchored 24-step difference-window scan of all 900
  samples (476,523 windows) found no shared windows.
- Rights: the saved project page was read directly; it states ODC-By 1.0 and
  the open access policy for the project files.
- Novelty: `novelty.py` on both resource URLs plus EHG-specific terms hit
  only this candidate. The EMG terms hit only the skeletal sEMG families.
