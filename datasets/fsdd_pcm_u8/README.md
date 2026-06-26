# Free Spoken Digit Dataset — 8-bit PCM (u8)

Unsigned 8-bit PCM audio amplitude of the Free Spoken Digit Dataset (FSDD) recordings, as
**one family** with **one sample per recording**. Fills a local gap: the downstream corpus
has `fsdd_pcm_u8`, while our collection had FSDD only at 16-bit (`fsdd_spoken_digits`).

- Source: https://github.com/Jakobovski/free-spoken-digit-dataset (8 kHz mono 16-bit WAV)
- Local raw payload: `${DATA_DIR:-.data}/extracted/fsdd_pcm_u8/.../recordings/`

## Family & samples

| family | quantity | type |
|---|---|---|
| `fsdd_pcm_u8` | audio amplitude (8-bit PCM) | uint8 |

- **A sample** = one recording's amplitude stream.
- Each 16-bit signed sample `s` is linearly requantized to unsigned 8-bit PCM:
  `((s + 32768) >> 8)` (silence → 128) — the standard 8-bit WAV convention.

## Run

```sh
bash datasets/fsdd_pcm_u8/download.sh   # ~20 MB GitHub archive
bash datasets/fsdd_pcm_u8/build.sh
bash datasets/fsdd_pcm_u8/verify.sh
```

Tuning env vars: `FSDD_URL`, `FSDD_MIN_RECORDS` (default 1000). Logs under
`${DATA_DIR:-.data}/logs/fsdd_pcm_u8/`.
