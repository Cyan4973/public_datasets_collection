# Musopen Chopin solo-piano 16-bit PCM development

## Outcome

Accepted `musopen_chopin_solo_piano_pcm_i16`. It holds 39 complete solo-piano recordings from Musopen's crowd-funded "Set Chopin Free" project, decoded bit-exact from FLAC to native signed 16-bit little-endian interleaved stereo PCM at 44.1 kHz.

This is the first real polyphonic music audio in the corpus, locally or downstream. Existing 16-bit `pcm_audio` families hold:

- speech: `librispeech_dev_clean_i16`, `fsdd_spoken_digits`
- isolated synthesizer and instrument notes: `nsynth_test_notes_i16`
- environmental clips: `esc50_environmental_audio_i16`
- phonocardiograms, bat vocalizations and machine sound

`maestro_midi_notes` is symbolic MIDI, not audio. The novelty is new content in an existing modality, not a new modality. zlsim measured the breadth verdict as OK.

## Source and rights

- Bulk source: Internet Archive item `musopen-chopin-complete-works-flac`. It has 214 FLAC tracks transcoded losslessly by XLD and libFLAC 1.3.3 from Musopen's ALAC release, plus the Musopen booklet. Every selected file is pinned by IA md5, size, STREAMINFO total_samples and the STREAMINFO MD5 signature in `scripts/pinned_files.tsv`.
- Download: 39 FLAC files, 277,179,034 bytes.
- License: CC0 1.0 / public domain.

The evidence chain was checked by `download.sh` and independently by the judge:

1. The 2013 Kickstarter campaign page (Wayback snapshot 20130908225009, sha256 `365d9aec…`) says in its FAQ: "What license will the music recordings be released under? … we will be using Creative Common's CC0 dedication".
2. Musopen's first-party IA item `musopen-chopin` was uploaded by aaron@musopen.org in 2015 with licenseurl CC0 1.0. MusicBrainz release ab46c4ff links to it as "download for free". That release belongs to release group 45aa5c1a, the same group embedded in the FLAC tags (LABEL=Musopen).
3. Musopen's own recording pages (judge check, Wayback 2024):
   - `musopen.org/music/82-preludes-op-28/` lists all 24 Jeannette Fang Op. 28 recordings with `rel="license"` set to the CC Public Domain Mark 1.0. Their durations equal the pinned files (no. 1 33 s, no. 15 316 s, no. 24 143 s, and so on).
   - `/music/4442-…op-45/` lists Fang's Op. 45 as PDM, 276 s.
4. Wikimedia Commons, Category:Set Chopin Free, holds the 12 Edward Neeman Op. 25 Etudes. For No. 1 the license is "Public domain" with Copyrighted False, and the duration of 159.553 s is identical to the file.
5. The bulk item itself declares licenseurl CC0 1.0.

The compositions are public domain (Chopin died in 1849). The recordings contain no personal data, and no credentials are used.

## Shape and conversion

Each natural record is one complete FLAC track, kept whole as one sample. Pieces are never concatenated, sharded or trimmed.

Selection, reproduced by `scripts/discover.sh` from 8 KiB STREAMINFO range reads:

- Candidates: all 52 Prelude/Etude FLACs.
- Kept: those at 44,100 Hz, 2 channels, 16 bps, which is 40 files.
- Excluded: the 12 Op. 10 Etudes, which are 48 kHz.
- Also excluded: Etude B. 130, the sole Donald Betts track. Its spectrum is band-limited (a brick-wall cutoff above ~16–18 kHz).
- Not in scope: the Cello Sonata and all other genres.

Conversion is `ffmpeg -map 0:a:0 -f s16le -acodec pcm_s16le`, with no resampling, remixing or dither. For every piece, build and verify both assert:

- decoded bytes == total_samples × 2 channels × 2 bytes
- MD5(decoded PCM) == the FLAC STREAMINFO MD5 signature

The pieces are fatal if constant, more than 50% zeros, more than 50% edge silence, dual-mono, lacking odd values, or have fewer than 1,024 distinct values.

## Accepted output

- Primary series: `chopin_solo_piano_pcm_s16_stereo` (int16, little-endian, interleaved L/R, 44.1 kHz)
- Samples: 39
  - 27 Preludes by Jeannette Fang: Op. 28 nos. 1–24, B. 86, Op. 45, "no. 27"
  - 12 Etudes Op. 25 by Edward Neeman
- Frames: 205,448,288 (4,658.69 s, 77.6 min)
- Primary values: 410,896,576
- Primary bytes: 821,793,152
- Sample size: 2,830,382 to 32,366,950 values (32.0 to 367.0 s); median 9,292,488 values
- Per-piece statistics:
  - zero fraction 0.20–2.79%
  - clipped values: 0
  - leading and trailing digital silence: 0 s
  - distinct values: 16,771–51,629

## Judge checks

- `python3 tools/autocollect/gate.py staging/musopen_chopin_solo_piano_pcm_i16`: PASS, no warnings.
- `bash staging/musopen_chopin_solo_piano_pcm_i16/verify.sh`: run by the judge and passed (39/39 MD5 bit-exact, index statistics recomputed). `build.sh` reads only the local pinned FLACs. The driver's `download.latest.log` shows 39 files and 277,179,034 B validated.
- Bytes, all 39 samples, standard-library Python:
  - RMS is -14 to -30 dBFS. Prelude peaks reach ±31–32.7k, so the full 16-bit range is used.
  - The LSB is set in 49.7–50.0% of values, with no missing codes in ±1000.
  - Every piece has a distinct 64-value window at 20 s, so there are no near-duplicates.
  - L/R correlation is ~0.45–0.69 for the Preludes and ~0–0.24 for the Etudes (wide-spaced microphones). Neither set is dual-mono.
- Spectra, pure-Python 4096-point FFT on 10 pieces:
  - No lossy-codec brick-wall.
  - The Preludes have a flat high-band floor up to an anti-alias step above 20.75 kHz, which stays above the 16-bit quantization floor.
  - The Etudes show noise-shaped dither rising toward Nyquist. That is a native mastering artifact.
  - The builder's B. 130 exclusion is consistent with this audit.
- Rights: I opened the Kickstarter snapshot, both IA metadata records, MusicBrainz release ab46c4ff (url-rels and tracklist), archived Musopen recording pages for Op. 28, Op. 45 and the Fang performer page, and the Commons file API for Neeman Op. 25 No. 1. Every selected file is covered by a first-party public-domain designation plus the project's CC0 commitment.
- Novelty:
  - `novelty.py` on the three resource URLs and the musopen/chopin/piano/music terms: only a host-only IA metadata recipe and the MAESTRO MIDI families.
  - `novelty.py --type pcm_audio`: 9 families, none of them music recordings.
  - zlsim OK. The nearest family is `hyg_star_absolute_mag_mmag_i16` (feature distance 0.04, compression loss 0.39, so not equivalent).
- Homogeneity: one unit, scale and lattice (16-bit linear PCM, 44.1 kHz stereo) and one generation process (microphone recordings of acoustic solo piano mastered to 16-bit by one producer). The difference between the two sessions in microphone spacing and dither shaping is within-material variation.
- Note for later: the recipe's evidence chain does not yet cite Musopen's per-recording Public Domain Mark pages. These are stronger than the project-wide statement the builder relied on for the Fang files. Adding them to the manifest notes would close the caveat the builder recorded.
