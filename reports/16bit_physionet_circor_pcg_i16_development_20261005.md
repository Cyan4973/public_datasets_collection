# PhysioNet CirCor DigiScope phonocardiogram int16 development

## Outcome

Accepted `physionet_circor_pcg_i16`. It holds every public heart-sound (phonocardiogram, PCG) recording in release 1.0.3 of the CirCor DigiScope Phonocardiogram Dataset on PhysioNet, one native int16 sample per auscultation recording.

This is a new instrument and source class within the known PCM-audio modality. Novelty kind: `new_source`.
- The local corpus already holds airborne-microphone PCM16 audio (`esc50_environmental_audio_i16`, `librispeech_dev_clean_i16`, `nsynth_test_notes_i16`, `openslr_rirs_noises_pcm16`).
- It also holds PhysioNet electrical and optical waveforms (`physionet_bidmc_ppg_resp_i16`, MIT-BIH ECG).
- This recipe adds contact-transducer cardiac acoustics: an electronic stethoscope chest piece, band-limited at 4 kHz.

No recipe, registry row, ledger row or downstream family contains phonocardiograms.

## Source and rights

- Source: anonymous PhysioNet open-data bucket, `https://physionet-open.s3.amazonaws.com/circor-heart-sound/1.0.3/` (pinned version, mirror of `physionet.org/files/circor-heart-sound/1.0.3/`).
- Release files are pinned by SHA-256:
  - `SHA256SUMS.txt` (957,290 B, `9724d3f0…`)
  - `LICENSE.txt` (20,402 B, `86c0ad30…`)
  - `RECORDS` (72,827 B, `953b0da0…`)
- Every one of the 6,326 `.wav`/`.hea` files is checked against `SHA256SUMS.txt`. Aggregate sizes are pinned: 578,849,274 B of WAV and 187,976 B of headers.
- License: Open Data Commons Attribution License 1.0. The release ships the ODC-By text as `LICENSE.txt`, which is itself listed in the release checksum file. This is the same license and open-access class as the accepted `physionet_bidmc_ppg_resp_i16`.
- Attribution:
  - Oliveira et al. 2022, IEEE JBHI 26(6):2524–2535, doi:10.1109/JBHI.2021.3137048
  - the PhysioNet dataset page
  - Goldberger et al. 2000
- Device: per the preprint, recordings were collected with a Littmann 3200 stethoscope with DigiScope Collector, "sampled at 4 KHz and with a 16-bits resolution".
- Safety: de-identified pediatric recordings from two screening campaigns (CC2014, CC2015) in Pernambuco, Brazil, named only by numeric study ID and site.
  - Only the waveform is emitted. Demographics, murmur and outcome labels, and segmentations are never downloaded.
  - Flags are `contains_sensitive_data = true` and `contains_personal_data = false`, following the accepted OpenNeuro and TCIA de-identified precedents.

## Shape and conversion

Each natural record is one complete auscultation recording: one WAV, `<patient>_<site>[_<n>].wav`. The 43 repeat recordings at a site are separate samples.

The helper converts each recording as follows:
1. Walk the RIFF chunk list, with no fixed-header assumption.
2. Require PCM tag 1, mono, 4000 Hz, 16-bit, byte rate 8000 and block align 2.
3. Cross-check the WFDB `.hea`: data offset `16+44`, sample count × 2 equals the data-chunk size, and the header site label matches the filename site.
4. Write the stored PCM codes as raw little-endian int16, with no gain, filtering or resampling.

Exclusion rule: fewer than 16 distinct codes, or a byte-identical payload. Nothing met it.

Full-scale samples are kept as recorded and reported, not masked.

The preprint states the signals are "normalized within the [-1;1] range". The bytes show this is not a per-recording peak normalization (`50782_MV_2` peaks at ±2,948) and left no code lattice. The emitted values are exactly the distributed int16 codes. The manifest and README do not mention this statement; a provenance note would be a worthwhile addition.

## Accepted output

- Source recordings validated: 3,163 (942 patients)
- Sites: AV 800, PV 766, TV 732, MV 861, Phc 4
- Exclusions: 0
- Primary samples: 3,163
- Primary values: 289,355,051
- Primary bytes: 578,710,102
- Sample length: minimum 20,608 values, median 85,824, maximum 258,048 (about 5–65 s at 4 kHz)
- Distinct codes per recording: 1,767–47,152 (median 6,545)
- Full-scale values: 83,638 (0.029%)
  - 1,970 recordings touch full scale at least once.
  - 17 recordings exceed 1% clipped values; the maximum is 4.35%.
- Aggregate output SHA-256: `42342b450a0e91f6442f2105ac0379ed4d47e2de97ab9886588f14a6be82a017`

## Judge checks

- **Gate:** `python3 tools/autocollect/gate.py staging/physionet_circor_pcg_i16` passed with no warnings.
- **Verify:** I ran `bash staging/physionet_circor_pcg_i16/verify.sh` myself and it passed in 24 s, reproducing every number above.
  - It re-decodes every WAV with the stdlib `wave` module and a separate header tokenizer.
  - It checks samples byte for byte, the index fields, the exclusion set, stray files, the aggregate hash and the manifest totals.
  - build.sh reads only `.data/downloads`.
- **Bytes** (stdlib `array`/`struct`, scripts under `/tmp/autocollect/physionet_circor_pcg_i16/`):
  - Values: 8 random samples show median |x| 104–518 and p99 1.3k–9.9k. Values have gcd 1 and uniform low 4 bits, so there is no lattice. DC is near zero.
  - Spectrum: 512-point FFT band energy extends to about 1.9 kHz and rolls off near Nyquist, so the audio is native 4 kHz, not upsampled.
  - Full scale: full-scale hits are runs of 1–2 at the peaks of fast high-amplitude oscillations, i.e. saturated transients.
  - Artifacts: only 7 recordings have more than 5% of values with |x| ≥ 30000, the worst being `84984_MV` with a saturated ~500 Hz artifact tone. That is a small minority.
  - Padding: the longest constant run in any recording is 8 values, so there is no padding or dropout.
  - Duplicates: content-anchored 12-value window hashing over all 289M values (2.1M landmarks) found 0 shared windows across or within recordings, so there are no near-duplicates or shifted copies.
  - Structure: `xxd` shows a plain 44-byte RIFF header that matches its `.hea` line.
- **Homogeneity:** patient-ID clusters (the likely campaigns) share one amplitude regime: median max|x| at or near full scale, 43–79% of recordings touching full scale, and median distinct codes 5.2k–8.1k.
- **Rights:**
  - The downloaded `LICENSE.txt` is the ODC-By text; its sha256 matches the pin and the release `SHA256SUMS.txt` line 1.
  - The bucket prefix lists anonymously, and no script contains credentials.
  - physionet.org and PMC returned 403 through this host's proxy, so the project page's access-policy wording was not re-read. The license file shipped in the release, the open-access bucket and the BIDMC precedent stand as the evidence.
  - Device, rate and resolution were confirmed from text extracted from the arXiv preprint (2108.00813).
- **Novelty:** `novelty.py --url <circor 1.0.3 prefix> --terms circor phonocardio "heart sound" digiscope stethoscope auscultation pcg murmur heart-sound` matched only this candidate's own staging and ledger rows. No audio or biosignal family has been accepted in this effort's ledger, so the breadth rule does not apply.
