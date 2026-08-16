# OpenSLR RIRS_NOISES measured room impulse responses — PCM16

This candidate targets room impulse responses from OpenSLR resource 28. The
database contains measured and simulated acoustic responses spanning multiple
rooms, source/microphone positions, and reverberation conditions.

Each retained WAV channel would become one variable-length signed-int16 sample.
The complete impulse response boundary is preserved; channels are not
concatenated, truncated, normalized, or requantized.

Metadata discovery established that the official resource page identifies the
release as Apache-2.0 and the archive contains 61,260 WAV members. The retained
subset is deliberately narrower than the whole release:

- 107 measured Aachen Impulse Response (AIR) WAV files;
- 36 measured REVERB-2014 RIR WAV files; and
- 182 measured RWCP RIR WAV files.

These 325 WAV files occupy 133,979,812 bytes including their containers. The
point-source and isotropic noise recordings are excluded, as are all 60,000
simulated responses. This keeps the family semantically focused on real
acoustic-system impulse responses and avoids flooding the corpus with synthetic
variants.

The metadata-only discovery stage:

- preserves the official OpenSLR resource page and its license text;
- reads the official ZIP end record and central directory through bounded HTTP
  byte ranges;
- inventories member paths, compression methods, sizes, CRCs, and coherent
  directory subcollections;
- estimates which complete subcollections fit the 1 GB decoded-output cap;
- range-decompresses only small prefixes of representative WAV members; and
- qualifies only integer PCM WAV files with exactly 16 stored and valid bits.

It never downloads the complete archive or a complete WAV member. Run:

```bash
bash datasets/openslr_rirs_noises_pcm16/discover.sh
```

Results are written under `.data/discovery/openslr_rirs_noises_pcm16/` and logs
under `.data/logs/openslr_rirs_noises_pcm16/`.

The official distribution is one 1,311,166,223-byte ZIP, so acquisition must
download it even though the selected real-RIR members are much smaller. The
download is resumable, pins the discovered size and ETag, rechecks the official
Apache-2.0 statement, inventories the exact 325 selected members, and records
the archive SHA-256:

```bash
bash datasets/openslr_rirs_noises_pcm16/download.sh
```

No WAV payload is decoded during acquisition. The subsequent build stage will
validate every selected WAV as 16-bit integer PCM, split multichannel files into
one sample per channel, preserve each complete response, and emit explicit
little-endian signed-int16 bytes.

After acquisition, build and verify the 3,810 channel samples:

```bash
bash datasets/openslr_rirs_noises_pcm16/build.sh
bash datasets/openslr_rirs_noises_pcm16/verify.sh
```

The build produces 133,959,032 primary bytes. Every output is a complete channel
from one measured response; lengths range from 1,667 to 159,792 int16 values.
