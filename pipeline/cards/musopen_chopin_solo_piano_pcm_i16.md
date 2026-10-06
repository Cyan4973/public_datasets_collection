# Musopen 'Set Chopin Free' Solo-Piano Recordings (CC0, Internet Archive): Preludes Op. 28 and Etudes, 16-bit 44.1 kHz Stereo PCM Decoded from FLAC

- Candidate id: `musopen_chopin_solo_piano_pcm_i16`
- Width: int16
- Quantity: Signed 16-bit stereo PCM amplitude of professionally recorded solo-piano performances (interleaved L/R at 44.1 kHz), decoded losslessly from FLAC files whose STREAMINFO declares 16 bits per sample.
- Source: https://archive.org/details/musopen-chopin-complete-works-flac
- Resources: https://archive.org/metadata/musopen-chopin-complete-works-flac, https://archive.org/download/musopen-chopin-complete-works-flac/Mazurka%20in%20B%20major%2C%20Op.%2063%20no.%201.flac, https://archive.org/download/musopen-chopin-complete-works-flac/
- License: CC0-1.0
- License evidence: https://archive.org/metadata/musopen-chopin-complete-works-flac
- License quote: licenseurl: https://creativecommons.org/publicdomain/zero/1.0/ ; description: "214 FLAC recordings of Chopin's complete works, produced by Musopen via Kickstarter (2012). Includes PDF booklet. CC0 public domain." Upstream intent (AV Club on Set Chopin Free): the campaign aimed "to record all of Chopin's compositions and make them available in the public domain."
- Natural record: One complete piece (one FLAC track) as interleaved stereo int16. The full 16-bit/44.1 kHz/stereo population is 110 pieces (6.23 h, 3.95 GB PCM), too big. Suggested coherent subset: all 16-bit/44.1 kHz files of the 24 Preludes Op. 28 (complete set) plus the 13 Etudes at that format = 37 pieces, ~74 min. Cello Sonata tracks (non-solo) and the 24-bit or 48/96 kHz files are excluded.
- Estimated samples: 37
- Estimated primary values: 392,000,000
- Estimated download bytes: 262,000,000
- Estimated primary bytes: 784,000,000
- Decode path: curl -L per-file download from archive.org/download/... (pin the IA md5 per file from the metadata JSON). Read FLAC STREAMINFO in pure Python (assert sr=44100, ch=2, bps=16, total samples). Decode with ffmpeg -i x.flac -f s16le -acodec pcm_s16le - (no resampling; LibriSpeech recipe precedent, flac CLI also accepted). Assert decoded value count == total_samples x 2. Emit little-endian int16.
- Novelty kind: new_content_same_modality
- Novelty evidence: novelty.py --url https://archive.org/details/musopen-chopin-complete-works-flac --terms musopen chopin: host-only match (internetarchive_advancedsearch metadata recipe); no recipe, registry, ledger or downstream matches. Local/downstream 16-bit audio is speech (LibriSpeech, FSDD), isolated instrument notes (NSynth), environmental clips (ESC-50), RIRs, bat calls, PCG and MIMII machine sound. Real polyphonic music recordings are absent (maestro_midi_notes is MIDI, not audio).
- Homogeneity: Solo acoustic piano only, one encoding regime (16-bit, 44.1 kHz, stereo) selected by STREAMINFO. Mixed 24-bit and 48/96 kHz files in the same item are excluded, as are cello-and-piano tracks. Several pianists and halls, but the same material type and scale.
- Risks: Audio already has 2+ new families this round (bat vocalizations, PCG; MIMII queued); this needs the 'no real music in corpus' justification. The IA item is a 2026 third-party upload (uploader alex.public.account) asserting CC0; musopen.org itself returned 403, so upstream public-domain intent rests on press coverage. Exact Preludes/Etudes file counts must be re-derived from STREAMINFO by the builder (probe found Preludes 24, Etude 13 at 16/44.1). Decoding depends on ffmpeg (or flac).
- Probe evidence: IA metadata JSON: 214 FLAC (152 'Flac' + 62 '24bit Flac'), per-file md5 present. Ranged STREAMINFO reads of all 214 files: (44100,2,16) n=110 6.23 h; (48000,2,16) n=22; (96000,2,16) n=20; 24-bit groups n=62. Genres at 16/44.1: Mazurka 44 (1.30 GB PCM), Preludes 24 (399 MB PCM, 145 MB FLAC), Etude 13 (385 MB PCM, 117 MB FLAC), others smaller. Range GETs via archive.org/download redirect worked (fLaC magic confirmed).

Proposed by the autocollect scout on 2026-10-06 (transcript `.data/pipeline/logs/scout_16bit/scout.20261006_035523.jsonl`).
