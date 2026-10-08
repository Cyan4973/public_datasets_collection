# MIMII valve 8-channel microphone-array int16 development

## Outcome

Accepted `zenodo_mimii_valve_mic_array_i16` from the Hitachi MIMII dataset (Zenodo record 3384388, version "public 1.0").

This is the corpus's first industrial machine-condition acoustics and its first interleaved multichannel microphone-array audio. The modality itself is not new: 16-bit PCM audio already has ESC-50, LibriSpeech, NSynth, FSDD, CirCor PCG and Rousettus, and the OpenSLR room impulse responses split channels into separate samples. The novelty label is therefore new content in a known modality. The measured breadth verdict is OK: the nearest family is downstream `chbmit_f8_t8_1d_var` (scalp EEG) at feature distance 0.0512 with compression loss 0.0024, just outside the 0.05 similarity threshold.

## Source and rights

- Source: Zenodo record https://zenodo.org/records/3384388 (doi:10.5281/zenodo.3384388), published 2019-09-20 by Purohit, Tanabe, Ichige, Endo, Nikaido, Suefusa and Kawaguchi (Hitachi, Ltd.), DCASE 2019 workshop paper (arXiv:1909.09347).
- Archive used: `6_dB_valve.zip`, 6,915,951,837 bytes, md5 `fe5fb7c337cd701b1d31dc641e621892` (ZIP64, 4,183 entries, 4,170 WAV members).
- Central-directory tail (bytes 6,915,459,463 to end, 492,374 B), sha256 `209786dc47b446d51160124a79a9e23a8600142e93fb79512ab08730cb9cd0ae`.
- License: CC BY-SA 4.0. The record description states "This dataset is made available by Hitachi, Ltd. under a Creative Commons Attribution-ShareAlike 4.0 International (CC BY-SA 4.0) license." The metadata license id is `cc-by-sa-4.0` and access_right is `open`. `download.sh` re-checks these fields, the version and the file pins. Attribution and ShareAlike obligations are recorded in the manifest and README.

## Shape and conversion

Each natural record is one complete 10-second WAV clip from a TAMAGO-03 8-microphone circular array placed 10 cm from an industrial solenoid valve. The publisher mixed real factory noise into each channel at 6 dB SNR relative to the mean power of that valve model's clips. This is the published product; the clean recordings are not published.

The recipe never downloads the archive whole. It range-fetches the central directory and then only the 160 selected member spans. Each span is processed as follows:

1. The local header is validated against the central directory, using the local header's own name and extra lengths.
2. The member is inflated with `zlib.decompressobj(-15)` to exactly 2,560,080 bytes, and the CRC32 is checked.
3. The RIFF chunks are walked (`fmt ,fact,data` in all 160).
4. The format must be exactly WAVE_FORMAT_EXTENSIBLE with 8 channels, 16 kHz, 16-bit samples, 16 valid bits and the PCM subformat GUID, with a 160,000-frame fact chunk and a 2,560,000-byte data chunk.
5. The data chunk is written unchanged: little-endian int16, interleaved frames with the channel index varying fastest, shape [160000, 8].

Selection is deterministic. Members are grouped by (model, condition), and the group sizes must match the paper's Table 1: id_00 991/119, id_02 708/120, id_04 1000/120, id_06 992/120 (normal/abnormal). Within each group, ordered by name, K members are taken at ranks floor((2k+1)N/(2K)), with K = 30 for normal and K = 10 for abnormal. Abnormal clips are deliberately over-represented: 25% of the selection against about 11% in the source.

## Accepted output

- Source WAV members: 4,170 (13 directory entries)
- Pinned and decoded members: 160 (40 per model: 30 normal, 10 abnormal)
- Exclusions: 0
- Primary samples: 160
- Values per sample: 1,280,000 (min = median = max)
- Primary values: 204,800,000
- Primary bytes: 409,600,000
- Download: 265,549,260 bytes
- Per-clip peak |x|: 2,578 to 16,675 (median 8,122); full-scale codes: 0
- Distinct codes per clip: 1,921 to 6,375 (median 4,028)
- Aggregate decoded SHA-256: `efd9215c50362b3918751d831e14d88742c19e4789717123d089193dd22ac754`

## Judge checks

- **Gate:** `gate.py staging/zenodo_mimii_valve_mic_array_i16` passed with no warnings.
- **Verify:** I ran `verify.sh` myself (Python 3.12.15). It passed: selftest ok, 160 samples, 0 excluded, matching aggregate sha256. It decodes every member a second time through stdlib `zipfile` and `wave`, independently of the build decoder. `build.sh` and `verify.sh` contain no network calls.
- **Bytes**, checked with stdlib `array` scripts under `/tmp/autocollect/`:
  - Every file is exactly 2,560,000 B.
  - Per-channel mean is about 0, and the low 2 bits are uniform (about 25% each), so the width is honest.
  - A 100 ms RMS envelope shows periodic valve-actuation transients (about 600 RMS every about 1.1 s in normal clips, irregular in abnormal clips) over a factory-noise floor of about 90 RMS.
  - Order-0 entropy is 8.44 to 9.12 bits per value.
  - Inter-channel correlation in an id_00 abnormal clip falls off circularly (0.975 for neighbours, 0.898 for opposite microphones), which confirms the interleave order on a circular array. No channels are identical.
  - Pairwise checks across 8 clips gave zero-lag correlation |r| < 0.05 and 0 of 1,650 shared 12-sample windows at any offset. There are no duplicated or reused segments, and no fill warnings.
- **Rights:** I fetched the Zenodo record JSON myself and confirmed the license id, the license sentence, open access, the version, and the file size and md5.
- **Novelty:** `novelty.py` with the record URL and the terms MIMII, ToyADMOS, DCASE, "machine sound", "microphone array", TAMAGO, "anomalous sound" and solenoid matched only the candidate itself. There were no registry or downstream hits. `--type pcm_audio` lists 8 existing families; no other family shares this instrument line.
- **Homogeneity:** one machine type, one SNR product, one array, one format and one code lattice. The noise floor is consistent across groups.
- **Volume:** 160 of 4,170 clips, 409.6 MB, which is above the roughly 100 MB downstream need and under the 1 GB cap. A 265.5 MB download yields 409.6 MB kept.
- **Host cap:** the per-host acceptance limit is enforced separately by the driver.
