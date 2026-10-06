# GRABMyo forearm/wrist surface-EMG int16 development

## Outcome

Accepted `physionet_grabmyo_semg_i16` from the immutable PhysioNet GRABMyo 1.1.0 release. 1.1.0 is the latest version; 1.0.0-1.0.2 also exist.

This is the first 16-bit EMG family. The only other EMG in the corpus is `uci_emg_gestures_i8` locally and `semg_channel_i8` downstream: Thalmic Myo armband codes at 8 bits, 200 Hz and 8 channels. GRABMyo is a different source and regime: a lab EMGUSB2+ amplifier at 2048 Hz with 28 electrodes, stored as full-range int16.

## Source and rights

- Source: the anonymous PhysioNet open-data bucket `https://physionet-open.s3.amazonaws.com/grabmyo/1.1.0/`.
- Pinned release files:
  - `SHA256SUMS.txt`: 4,300,947 B, sha256 `757ea64fa5134b7b3b84d9f79e30cfa1ac4d2c65a40ce9b427db11dd8258974e`;
  - `LICENSE.txt`: 14,842 B, sha256 `9a78e7f22742dde9f66ae235ec793ba2212019dc4d0ced75c4da09ced0b35fb2`;
  - `readme.txt`;
  - `MotionSequence.txt`.
- Trial selection: every `Session1/*_trial1.dat|.hea` entry of `SHA256SUMS.txt`, which must form the complete 43 x 17 grid. The selection is pinned by sha256 `ad6d952e14967043c9927534e834cf62f9b63676f3c0930a80ebbed99a0423dc`.
- License: CC BY 4.0.
  - The project page says "Anyone can access the files, as long as they conform to the terms of the specified license." It is open access with no credentialing.
  - The release `LICENSE.txt` is the CC BY 4.0 legal code.
  - The bundled readme names ODC-By 1.0, which is also attribution-only.
- Attribution:
  - Jiang, Pradhan & He (2024), doi:10.13026/89dm-f662;
  - Pradhan, He & Jiang (2022), Sci Data 9:733;
  - Goldberger et al. (2000).
- Safety: pseudonymous healthy volunteers. `subject-info.csv` is not downloaded, and the headers carry no comment lines.

## Shape and conversion

Each natural record is one complete 5-second gesture trial: a WFDB format-16 `.dat` of 10,240 frames x 32 signals, 655,360 B.

The recipe keeps the 28 electrode channels, `F1`-`F16` (forearm, two rings of eight) and `W1`-`W12` (wrist, two rings of six). It drops `U1`-`U4` (columns 17, 24, 25, 32), which the project page lists as unused inputs. The kept columns are written in source order, frame-interleaved, as raw little-endian int16. Values are byte-identical to the stored source cells.

Headers are strictly validated: record line `<name> 32 2048 10240`, format 16, ADC resolution 16, ADC zero 0, units mV, and fixed channel order. All 32 per-signal WFDB checksums and initial values are checked in every file.

The stored values are not raw ADC codes. The publisher band-pass filtered the signal (10-500 Hz) and applied a 60 Hz notch, then auto-scaled each channel of each file to the full int16 range when writing WFDB. Physical gain therefore spans 7,099.654-3,379,771.645 codes/mV (median 125,106.416). Per-channel gains and baselines are kept only in the auxiliary index.

## Accepted output

- Source trials validated: 731 (43 participants x 17 gestures; 16 movements plus Rest)
- Excluded trials: 0
- Primary samples: 731
- Values per sample: 286,720 (10,240 x 28); 573,440 B each
- Primary values: 209,592,320
- Primary bytes: 419,184,640
- Download: 1,462 record files (479,068,160 B of `.dat` and 2,273,949 B of `.hea`); 485,909,830 B under `downloads/`
- Global code range: -32767 to 32766. Channel minimum is -32767 in 19,831 channels and -32766 in 637.
- Smallest per-channel distinct count: 3,562
- Channel peak-to-peak: median 550.6 µV in gesture trials (31.1-9,230.4) and 102.3 µV in Rest trials (19.4-1,487.4)
- Aggregate output SHA-256: `d70a0eff7a6a6332f5799e3b2163197401ed9ff42c4a577af41cc9e786ff919b`

The local build and independent byte-for-byte verification both completed successfully against the pinned files.

## Judge checks

- **Gate:** `tools/autocollect/gate.py` PASS, no warnings.
- **Verify:** I ran `verify.sh` myself: `verify=ok` in 36.6 s with the same aggregate hash. `build.sh` reads only `.data/downloads`, and no script holds credentials.
- **Bytes (stdlib `array`/`struct`):**
  - **Per-channel statistics on 10 samples:** each channel is zero-mean about its baseline. Lag-1 autocorrelation is 0.80-0.95 and H0 about 12.7-13.0 bits per channel.
  - **Duplicates:** all 20,468 kept channels were hashed. There are 0 exact duplicates and 0 first-difference-fingerprint duplicates, and no duplicate channels within a sample.
  - **Extremes:** each channel's extremes occur once (4 channels reach their maximum twice), so there is no clipping, and there are no -32768 values.
  - **Low bits:** uniform low-byte, parity and mod-4 histograms, so there is no lattice and no widening.
  - **Spectrum (Goertzel, relative to 100 Hz):**
    - 60 Hz is at -18.5 dB, against -5.6 and -4.7 dB at 58 and 62 Hz, confirming the notch;
    - 2 Hz is at -33.6 dB and 5 Hz at -28.8 dB;
    - 600 Hz is at -34.6 dB and 800 Hz at -53.5 dB.

    This confirms the claimed publisher filtering.
  - **Cross-channel structure:** adjacent forearm correlation medians run 0.76-1.00 across 12 trials. This is natural multichannel redundancy.
  - **Generic compressibility:** zlib-9 gives 1.02-1.04x and xz-6 1.02-1.06x. The material is hard but genuine.
- **Rights:** I fetched the project page and confirmed CC BY 4.0 with open access. I checked the first line of `LICENSE.txt` and the readme's ODC-By wording. The bucket listing shows 1.1.0 is the latest version.
- **Novelty:** `tools/autocollect/novelty.py` found no GRABMyo or 16-bit EMG in local, staging, registry, ledger or downstream layers. The only EMG is the 8-bit Myo family.
- **Homogeneity:** one study, amplifier, montage, rate and publisher encoding. Physical gain varies, but in stored-value terms all channels, Rest included, are the same full-range dense quantization.
- **Note:** the project page describes the montage as both "monopolar electrodes … forming bipolar pairs" and "channels … in a bipolar configuration". The manifest quotes the publisher accurately, and the high inter-channel correlation suggests a common-reference component. No recipe change is needed.
