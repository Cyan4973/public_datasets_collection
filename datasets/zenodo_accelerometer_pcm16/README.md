# Honeybee Accelerometer PCM16

This recipe contains physical honeybee-vibration measurements from an
accelerometer, published as a mono PCM16 WAV.

The strict decoder requires a canonical little-endian RIFF/WAVE declaration
using integer PCM format 1, one channel, 48 kHz, 16 bits per sample, and exact
source/payload hashes.

Run:

```bash
bash datasets/zenodo_accelerometer_pcm16/download.sh
bash datasets/zenodo_accelerometer_pcm16/inspect.sh
bash datasets/zenodo_accelerometer_pcm16/build.sh
bash datasets/zenodo_accelerometer_pcm16/verify.sh
```

Zenodo record `7018660`, *Audio D18*, explicitly documents its only WAV as one
minute of physical accelerometer data containing honeybee vibrations. It is a
CC BY 4.0 mono PCM16 file at 48 kHz, constructed by concatenating 60 source
points where each point is exactly one second of accelerometer data. The
natural samples are therefore 60 fixed-size 48,000-value segments,
not the artificial one-minute listening concatenation.
