# LibriSpeech Dev-Clean PCM16

This staging recipe collects the LibriSpeech `dev-clean` split and emits one raw little-endian signed 16-bit PCM sample per utterance.

The source material is native speech audio distributed as FLAC. `build.sh` decodes each FLAC file locally and preserves the utterance boundary as the sample boundary. It does not concatenate utterances.

Expected scale before local validation:

- Natural samples: about 2,700 utterances.
- Primary output: about 600-650 MB of raw PCM16.
- Size profile: variable utterance durations, unlike fixed-size speech-command clips.
- Required local decoder: `flac` or `ffmpeg`.

Run:

```bash
staging/librispeech_dev_clean_i16/download.sh
staging/librispeech_dev_clean_i16/build.sh
staging/librispeech_dev_clean_i16/verify.sh
```

No dataset payload is committed. All local files are written under `${DATA_DIR:-.data}`.
