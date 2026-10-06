# PhysioNet GRABMyo Forearm/Wrist Surface EMG Hand-Gesture Trials Int16

- Candidate id: `physionet_grabmyo_semg_i16`
- Width: int16
- Quantity: Monopolar surface EMG (mV) from 16 forearm and 12 wrist electrodes, EMGUSB2+ amplifier, 2048 Hz, 5-second hand-gesture trials, stored WFDB format-16 codes
- Source: https://physionet.org/content/grabmyo/1.1.0/
- Resources: https://physionet-open.s3.amazonaws.com/grabmyo/1.1.0/Session1/, https://physionet-open.s3.amazonaws.com/grabmyo/1.1.0/SHA256SUMS.txt, https://physionet-open.s3.amazonaws.com/grabmyo/1.1.0/LICENSE.txt
- License: CC BY 4.0 (PhysioNet project license; the bundled readme also names ODC-By 1.0, which is likewise attribution-only)
- License evidence: https://physionet.org/content/grabmyo/1.1.0/
- License quote: Anyone can access the files, as long as they conform to the terms of the specified license. License Creative Commons Attribution 4.0 International Public License
- Natural record: One complete gesture trial file (session/participant/gesture/trial): 10,240 frames x 32 signals. Keep the 28 named electrodes F1-F16 and W1-W12 (286,720 values), with U1-U4 auxiliary or dropped.
- Estimated samples: 731
- Estimated primary values: 209,592,320
- Estimated download bytes: 479,068,160
- Estimated primary bytes: 419,184,640
- Decode path: curl the pinned trial .hea/.dat pairs and verify them against SHA256SUMS.txt. Parse the header: 32 signals, format 16, 2048 Hz, 10,240 samples. Read the .dat (exactly 655,360 bytes) as array('h') LE, de-interleave stride 32 and keep the indices named F*/W*. Check the per-signal checksum.
- Novelty kind: new_source
- Novelty evidence: There is no EMG at 16 bits locally or downstream: novelty.py found no grabmyo or EMG-16 hits. The only EMG in the corpus is uci_emg_gestures_i8 (8-bit Myo armband codes, a different device and width). GRABMyo is a new source, and its 2048 Hz high-resolution EMG is a different regime from the 200 Hz int8 Myo.
- Homogeneity: All 15,351 trial files are exactly 655,360 bytes with an identical 32-signal layout. Suggested bounded subset: Session 1, all 43 participants, all 17 gestures, trial 1 = 731 trials (~0.48 GB download). Same amplifier, electrode montage and sampling rate throughout. Range probes show dense step-1 code lattices (~960-980 distinct values per 1,000 samples on every channel).
- Risks: Per-file, per-signal gains (e.g. 109223.8/mV vs 176520.4/mV) indicate the codes were auto-scaled from float data when converted to WFDB (each channel spans nearly the full int16 range), so code scale is not constant across files. The judge may weigh this, as with the CEBS-style concern, but here the lattice is dense, not upsampled. U1-U4 'unused' channels carry signal and must be excluded or labelled. This is the third physiological-signal proposal this round; its quantity (sEMG) differs from ICP and EHG.
- Probe evidence: S3 listing: 15,351 .dat files, all 655,360 bytes (10.06 GB total; page: 9.4 GB), across 43 participants x 3 sessions x 17 gestures x 7 trials. Headers show 32 signals F1-F16, U1, W1-W6, U2, U3, W7-W12, U4, format 16, 2048 Hz, 10,240 samples. A 64 KB range GET on session1_participant1_gesture10_trial1.dat decoded to dense int16 EMG on all channels. LICENSE.txt is the CC BY 4.0 legal code, and the readme cites the EMGUSB2+ amplifier.

Proposed by the autocollect scout on 2026-10-05 (transcript `.data/pipeline/logs/scout_16bit/scout.20261005_215706.jsonl`).
