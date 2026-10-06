# PhysioNet CirCor DigiScope Pediatric Phonocardiogram Recordings PCM16

- Candidate id: `physionet_circor_pcg_i16`
- Width: int16
- Quantity: Phonocardiogram (heart sound) amplitude: 4 kHz mono 16-bit PCM from an electronic stethoscope at the aortic, pulmonary, tricuspid and mitral auscultation sites
- Source: https://physionet-open.s3.amazonaws.com/circor-heart-sound/1.0.3/
- Resources: https://physionet-open.s3.amazonaws.com/circor-heart-sound/1.0.3/SHA256SUMS.txt, https://physionet-open.s3.amazonaws.com/circor-heart-sound/1.0.3/RECORDS, https://physionet-open.s3.amazonaws.com/circor-heart-sound/1.0.3/LICENSE.txt, https://physionet-open.s3.amazonaws.com/circor-heart-sound/1.0.3/training_data/13918_MV.wav, https://physionet-open.s3.amazonaws.com/circor-heart-sound/1.0.3/training_data.csv
- License: ODC-By 1.0 (Open Data Commons Attribution License); same license as accepted PhysioNet recipes physionet_bidmc_ppg_resp_i16, eeg_physionet and mitbih_arrhythmia_u8
- License evidence: https://physionet-open.s3.amazonaws.com/circor-heart-sound/1.0.3/LICENSE.txt
- License quote: # ODC Attribution License (ODC-By) ... The Open Data Commons Attribution License is a license agreement intended to allow users to freely share, modify, and use this Database subject only to the attribution requirements set out in Section 4.
- Natural record: One auscultation recording = one WAV file (<patient>_<site>.wav, e.g. 13918_MV.wav), the complete int16 PCM data chunk. The median is ~115K samples (~29 s); range ~26K-186K samples.
- Estimated samples: 1,000
- Estimated primary values: 102,900,000
- Estimated download bytes: 206,000,000
- Estimated primary bytes: 205,800,000
- Decode path: curl the pinned WAVs (sha256 from SHA256SUMS.txt) from the training_data/ prefix. Parse RIFF/WAVE in pure stdlib: fmt PCM tag 1, 1 channel, 4000 Hz, 16 bits. The data chunk is little-endian int16. Cross-check against the WFDB .hea ('<rec>.wav 16+44 1 16 ...', 4000 Hz, sample count).
- Novelty kind: new_quantity
- Novelty evidence: novelty.py --url on the circor 1.0.3 prefix and terms 'circor', 'phonocardio', 'heart sound', 'physionet-open' returned no matches in recipes, registry, ledger or downstream. Existing PhysioNet families are ECG/EEG/PPG/respiration waveforms. Audio PCM16 families (ESC-50, LibriSpeech, NSynth, FSDD, RIRs) are airborne sound, not chest-wall cardiac acoustics recorded at 4 kHz.
- Homogeneity: One study, one device type (electronic stethoscope, as the dataset documents), one sampling rate and bit depth, one quantity. The four or five auscultation sites are the same measurement process at different chest locations. No mixing with other PhysioNet heart-sound sets (CinC 2016, EPHNOGRAM), which use different devices and rates.
- Risks: (1) Outside this round's focus domains. (2) The judge may see it as close to existing PCM16 audio; the cardiac acoustic content and 4 kHz rate are distinct, but the claimed novelty is new_quantity, not new modality. (3) Human pediatric subjects: de-identified, distributed as PhysioNet open access (no credentialing) under ODC-By, like the accepted MIT-BIH/BIDMC recipes. Emit only waveform values, no demographics. (4) Population is 3,163 recordings (~651 MB primary), under the 1 GB cap. A deterministic ~1,000-recording subset (all sites for the lowest patient IDs) gives ~200 MB; the builder may take the full set if the judge prefers whole-population scope. (5) Pin version 1.0.3 rather than a mutable latest path.
- Probe evidence: PhysioNet's open-data S3 bucket listing (253 projects) includes circor-heart-sound/1.0.0-1.0.3. The 1.0.3 root has LICENSE.txt (20,402 B, ODC-By text fetched), RECORDS, SHA256SUMS.txt (lists 3,163 .wav) and training_data.csv. The first 1,000-key page of training_data/ had 303 WAVs: min 52,780 B, median 230,316 B, max 372,012 B, mean 205,814 B. A one-byte -L range GET on 13918_MV.wav returned 206. The first 64 bytes show a RIFF/WAVE header with fmt PCM, 1 channel, 4000 Hz (0x0FA0), byte rate 8000, block align 2, 16 bits, data chunk 230,272 B. The .hea reads '13918_MV 1 4000 115136 / 13918_MV.wav 16+44 1 16 0 0 0 0 MV'.

Proposed by the autocollect scout on 2026-10-05 (transcript `.data/pipeline/logs/scout_16bit/scout.20261005_180613.jsonl`).
