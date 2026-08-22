# Asterisk Core Sounds G.711 mu-law Uint8 — 2026-08-22

## Outcome

`asterisk_core_sounds_ulaw_u8` adds 558 English telephony-prompt recordings
containing 11,789,778 native unsigned-byte G.711 mu-law codes. Natural prompt
samples range from 1,600 to 586,790 codes, with a median of 10,955, clearing
both aggregate and median-sample acceptance floors.

The corpus already contains linear unsigned 8-bit PCM spoken digits. This
family adds a materially different operational numeric representation: G.711
mu-law's standardized nonlinear amplitude companding and code mapping, applied
to a much broader vocabulary of professionally recorded telephony prompts.

## Source and rights

The source is the versioned official English Asterisk Core Sounds 1.6.1 mu-law
release. The recipe pins the 10,241,447-byte archive by exact SHA-256.

The embedded `LICENSE-asterisk-core-en-1.6.1` is also pinned by size and hash.
It identifies the voice prompts as copyright 2003–2008 Allison Smith and
grants the Creative Commons Attribution-ShareAlike 3.0 Unported license. That
license permits commercial reproduction and adaptation but requires
attribution and imposes share-alike conditions on derivative distributions;
users of the training material must preserve and assess those obligations.

## Natural boundaries and conversion

Each `.ulaw` member is already a headerless stream of one-byte G.711 mu-law
codewords sampled at 8 kHz. One source prompt file is therefore one natural
sample. Each code has direct standardized numeric meaning as a companded audio
amplitude; TAR framing and metadata are not emitted.

The recipe preserves every selected code in source order without linear-PCM
decoding, resampling, requantization, normalization, concatenation, or other
numeric transformation. The package's ten explicit `silence/1.ulaw` through
`silence/10.ulaw` utility streams are excluded from the spoken-prompt scope.
No exact duplicate prompt streams were found.

## Verification

Build and verification passed on 2026-08-22. Verification reparses the exact
pinned release and embedded license, reconstructs all selected prompt streams,
checks uint8 schema and natural boundaries, byte-compares all 558 outputs with
the fresh archive parse, and requires exact agreement among source-derived
profiles, index rows, ingest statistics, hashes, and sample-directory
contents.
