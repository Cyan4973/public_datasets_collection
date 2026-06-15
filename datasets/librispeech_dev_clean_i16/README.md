# LibriSpeech Dev-Clean PCM16

Collects the LibriSpeech `dev-clean` split and emits one raw little-endian
signed 16-bit PCM sample per utterance.

The source material is speech audio distributed as lossless FLAC. `build.sh`
decodes each FLAC file locally and preserves the utterance boundary as the
sample boundary. It does not concatenate utterances.

```bash
datasets/librispeech_dev_clean_i16/download.sh
datasets/librispeech_dev_clean_i16/build.sh
datasets/librispeech_dev_clean_i16/verify.sh
```

Expected validated scale:

- Natural samples: 2,703 utterances.
- Primary output: 620,675,864 bytes of raw PCM16.
- Size profile: variable utterance durations, not fixed-size clips.
- Required local decoder: `flac` or `ffmpeg`.

