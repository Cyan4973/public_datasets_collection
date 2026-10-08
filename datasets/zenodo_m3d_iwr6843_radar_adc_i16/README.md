# zenodo_m3d_iwr6843_radar_adc_i16

Raw FMCW radar IF ADC samples (native int16) from the **M3D Motion -
Millimeter-Wave Motion and Dynamics Dataset** (G. Marinaro, VSB - Technical
University of Ostrava), Zenodo record
[22811456](https://zenodo.org/records/22811456), CC-BY-4.0.

A TI IWR6843AOP 60 GHz radar observed one person walking (straight or in a
square path) or doing squats. A TI DCA1000 board recorded the raw ADC stream.
This recipe collects **all 16 captures recorded with one exact chirp
profile at a 100 ms frame period**. Each capture file is one sample.

## Source and pinning

- Record JSON: `https://zenodo.org/api/records/22811456`. License
  `cc-by-4.0`, one file `dataset_260917.zip` of 3,712,631,577 bytes,
  md5 `ce7e75179bcabac8fd3f934f75a863f4`. The record was published on
  2026-09-17 and is the second version of concept 21802511. The earlier
  version is record 21802513 / `dataset_260807.zip`.
- The archive is never downloaded whole. `download.sh` range-GETs the last
  64 KiB and requires the pinned central directory: 349 entries, offset
  3,712,592,250, 39,305 bytes, SHA-256 `7038083082f3...064f4f`. It then
  range-GETs only the members it needs.
- Zenodo publishes no per-member checksums. The central-directory CRC-32s and
  sizes (repeated in `selection.tsv`) are the pins, and every member is
  inflated and CRC-checked.

## Selection (re-derived by `download.sh` and compared with `selection.tsv`)

A capture `<session>/<nn>/datacard_record_hdr_0ADC_0.bin` is kept when its
`conf_file.cfg` contains exactly:

```
dfeDataOutputMode 1
channelCfg 15 7 0
adcCfg 2 1
adcbufCfg -1 0 1 1 1
profileCfg 0 61.2 60 17 50 657930 0 55.27 1 64 2000 2 1 36
chirpCfg 0 0 0 0 0 0 0 1
chirpCfg 1 1 0 0 0 0 0 2
chirpCfg 2 2 0 0 0 0 0 4
frameCfg 0 2 L 0 100 1 0        (L = 48 or 64 loops, 100 ms frames)
lvdsStreamCfg -1 1 1 1
```

Its DCA1000 `LogFile.csv` must also report a complete 0ADC stream: 0
out-of-sequence packets, 0 zero-filled packets/bytes, and received packets
equal to file size / 1088.

| group | captures | loops | chirps/capture | label (legend) |
|---|---|---|---|---|
| 260722/07 | 1 | 48 | 48,000 | walking in a squared path |
| 260722/08-10 | 3 | 64 | 48,000 | walking in a squared path |
| 260729/00-06 | 7 | 48 | 24,000 (00) / 48,000 | walking (radar in a corner, tilted 45 deg) |
| 260730/00-04 | 5 | 48 | 48,000 / 24,000 (04) | walking (00-01), squats (02-04) |

**Loops per frame (48 vs 64) is the only variation between selected
captures.** It changes only how many TX0/TX1/TX2 chirp triplets follow each
other before the inter-frame gap. Every chirp record has the same profile,
the same 1,088-byte layout and the same header. If a stricter group is
preferred, the 13 captures at 48 loops (590 MB) can be used alone.

Excluded, not mixed in:
- 4 captures with the same chirp profile but 224 loops and 120 ms frames
  (260722/00-03, 862.8 MB). These would break the 1 GB cap and differ in
  frame timing.
- 11 captures with no `conf_file.cfg`, whose profile cannot be confirmed:
  250529/08-11 hold only an Italian note "same config as 03", and
  260720/01-04,06-08 have no config at all.
- 49 captures in 5 other configurations: 96-, 128- or 256-sample profiles,
  2-TX chirping, 55 ms frames.

**Sample count is source-limited.** 16 is below the ~20 guideline, but it is
every capture of this profile at 100 ms frames. The next-largest homogeneous
group (18 captures, 96-sample profile, 55 ms frames) is 2.7 GB raw and would
need a different recipe.

## Record format and conversion

DCA1000 raw capture with HSI headers: a sequence of 1,088-byte chirp
records.

- bytes 0-63: HSI header. It starts with the magic `0x0CDA0ADC0CDA0ADC` and is
  byte-identical in every chirp of every selected capture: hex
  `dc0ada0cdc0ada0c300400000000000080072000040200020f0101008000`, then 22
  zero bytes, then 12 bytes `0x0f`. It carries no counter. It is validated and
  **dropped** (46,080,000 bytes in total).
- bytes 64-1087: payload of 512 little-endian int16 values, emitted unchanged.

Payload layout, documented but emitted as stored: `adcbufCfg -1 0 1 1 1`
selects complex output, sampleSwap = 1 (Q in the low half-word, I in the
high half-word) and non-interleaved channels. Each payload is therefore
`RX0[64 complex] RX1[64] RX2[64] RX3[64]`, each complex sample stored as
`Q, I` int16, following TI's adcbufCfg documentation. The RX-block structure
is confirmed empirically: a ramp-end transient (about -1,900 / +3,900) appears
only at the last complex sample of each 128-value block (int16 positions
126/127, 254/255, 382/383, 510/511). The Q/I order inside a pair comes from
the documentation and was not independently measured. Chirps follow
TX0, TX1, TX2 (chirpCfg 0-2) repeated L times per frame. Captures stop on a
DCA1000 packet-count limit (24,000 or 48,000 chirps), not on a frame
boundary.

Each sample is `samples/zenodo_m3d_iwr6843_radar_adc_i16/m3d_iwr6843_hsi_adc_iq_i16/<session>_<nn>.bin`:
24,000 x 512 = 12,288,000 or 48,000 x 512 = 24,576,000 int16 values. The
total is 16 samples, 368,640,000 values and 737,280,000 bytes. Index rows add
session, capture, legend label, frame_loops, chirps, min, max and sha256.

Realized output (verify.sh, 2026-10-08):

| measure (per sample) | range |
|---|---|
| min / max | -4,069..-4,033 / 3,951..4,002 |
| distinct int16 codes | 1,786-2,222 |
| zero fraction | 0.6-1.4% |
| all-zero chirps | 0 |

Values cluster near zero, with the per-RX ramp-end transient near the rails of
the ±4k range. The full int16 range is never used, but this is the native ADC
output, not widening.

## Scripts

- `download.sh`: record check, central-directory pin, 158 small metadata
  members, re-derived selection (fatal if it differs from `selection.tsv`),
  then 16 resumable exact byte ranges (453,565,185 bytes). Each range is fully
  inflated and checked: CRC-32, size % 1088, every HSI header, and
  non-degeneracy. About 454 MB in total under
  `.data/downloads/zenodo_m3d_iwr6843_radar_adc_i16/`.
- `build.sh`: local files only. It re-checks config and log, stream-inflates,
  checks the CRC and headers, and writes payloads, the index and
  `filtered/.../ingest_stats.json`.
- `verify.sh`: an independent implementation (`scripts/verify_samples.py`)
  re-derives every sample byte for byte from the ZIP ranges and re-checks the
  config and log. It recomputes min/max/SHA-256 and the full distinct count
  (>= 1000), rejects constant or degenerate samples (>= 1% all-zero chirps,
  > 5% zeros, or clipping at both rails), and checks index and manifest
  totals.
- `scripts/selftest_synthetic.py <workdir>`: builds a synthetic DEFLATE ZIP
  with the same member layout (including decoys) and runs CD parsing,
  extraction, derivation, build and the independent verifier on it, plus
  negative tests for CRC, header and partial records. Run it from a scratch
  directory.

All parsing is pure Python stdlib (`struct`, `zlib`, `array`); network I/O is
curl only.
