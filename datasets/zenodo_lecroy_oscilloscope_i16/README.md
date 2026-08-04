# Zenodo LeCroy Oscilloscope Int16 — Discovery

This candidate searches Zenodo for direct LeCroy `.trc` oscilloscope files
whose waveform payloads are native signed 16-bit ADC samples. The intended
natural record is one complete acquisition channel, or one declared sequence
segment when the source explicitly stores multiple subarrays.

This would add laboratory electrical-voltage and transient waveforms rather
than another acoustic, physiological, accelerometer, or RF I/Q source.

Run:

```bash
bash staging/zenodo_lecroy_oscilloscope_i16/discover.sh
```

The discovery script:

- queries Zenodo metadata for direct `.trc` files;
- requires an explicit CC0 or CC BY license;
- bounds candidate files between 4 KiB and 1 GiB;
- range-reads at most the first 128 KiB from at most 40 candidates; and
- requires a valid `WAVEDESC` header, `COMM_TYPE=WORD`, declared byte order,
  bounded descriptor blocks, and a waveform array consistent with the source
  file size.

It does not download complete waveform payloads. Results are written under
`.data/discovery/zenodo_lecroy_oscilloscope_i16/`.

Discovery found one coherent CC BY 4.0 source, Zenodo record `7939431`, with
21 qualifying little-endian WORD traces. They represent seven synchronized
RF/optical channels for each of three hypervelocity-impact shots and contain
15,000,034 declared int16 values in 30,007,565 source bytes.

Download and inspect the pinned record:

```bash
bash datasets/zenodo_lecroy_oscilloscope_i16/download.sh
bash datasets/zenodo_lecroy_oscilloscope_i16/inspect.sh
bash datasets/zenodo_lecroy_oscilloscope_i16/build.sh
bash datasets/zenodo_lecroy_oscilloscope_i16/verify.sh
```

The downloader revalidates the record's CC BY 4.0 license, exact 21-file TRC
inventory, aggregate source bytes, and every Zenodo-provided MD5. The inspector
strictly parses every complete file and reports value ranges, distinct counts,
transitions, duplicates, and zlib ratios before any training samples are
emitted.

Build extracts each complete `WAVE_ARRAY_1` as one sample. All accepted files
are little-endian, contain one declared subarray, and end exactly after the
waveform payload, so the emitted int16 bytes are source-identical.

A later payload preflight must validate the complete file, extract only the
declared `WAVE_ARRAY_1` signed-int16 values, preserve sequence-segment
boundaries, and reject constant, truncated, ambiguous, or duplicate traces.
Physical scaling fields may be retained as metadata, but the primary training
series should remain the source-native ADC integers.
