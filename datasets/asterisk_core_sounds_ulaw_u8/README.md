# Asterisk Core Sounds G.711 mu-law Uint8

This staged recipe targets the English Asterisk Core Sounds release encoded as
raw G.711 mu-law (`.ulaw`) audio. Each source file is a headerless stream of
native one-byte companded audio codes, sampled at the telephony rate. One
spoken prompt is one natural one-dimensional sample.

This differs from the existing linear unsigned-PCM spoken-digit family. G.711
mu-law applies a standardized nonlinear amplitude companding curve and bit
encoding, producing a materially different byte distribution while retaining
direct per-sample numeric meaning.

The recipe excludes the package's dedicated `silence/` utilities from the
spoken-prompt scope and retains the first occurrence of each exact duplicate
code stream. It does not decode, requantize, normalize, concatenate, or alter
the mu-law codes.

Run:

```bash
bash staging/asterisk_core_sounds_ulaw_u8/download.sh
bash staging/asterisk_core_sounds_ulaw_u8/build.sh
bash staging/asterisk_core_sounds_ulaw_u8/verify.sh
```

The release archive and its embedded license are pinned by exact size and
SHA-256. It yields 558 prompt samples containing 11,789,778 mu-law codes, with
a median natural sample of 10,955 codes. Ten dedicated silence utilities are
excluded from the spoken-prompt scope.
