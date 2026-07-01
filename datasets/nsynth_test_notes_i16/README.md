# NSynth Test Notes PCM16

This recipe collects the NSynth test split and emits one raw signed 16-bit PCM sample per note WAV file.

The source material is musical-instrument note audio from Magenta/Google. This is intentionally different from speech audio: the natural sample is one synthesized/acoustic instrument note recording.

Expected shape:

- About `4,096` note samples in the test split.
- Each sample is expected to be fixed duration, so size diversity is weak.
- Raw output is expected around `500-600 MB`.

Run:

```bash
datasets/nsynth_test_notes_i16/download.sh
datasets/nsynth_test_notes_i16/build.sh
datasets/nsynth_test_notes_i16/verify.sh
```

No dataset payload is committed. All local files are written under `${DATA_DIR:-.data}`.
