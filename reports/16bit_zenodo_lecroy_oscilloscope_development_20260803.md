# Zenodo LeCroy Oscilloscope Int16 Development — 2026-08-03

`zenodo_lecroy_oscilloscope_i16` adds laboratory electrical and optical
transient measurements as native signed-16-bit series. The source contains
LeCroy oscilloscope acquisitions from RF patch antennas and a photomultiplier
tube during hypervelocity dust impacts. This generation process differs from
audio PCM, accelerometers, physiological signals, RF I/Q recordings, and
tabular sensor observations already represented in the corpus.

## Source and license

Metadata and bounded-header discovery examined 57 Zenodo records and found one
coherent qualifying source: record `7939431`, *Hypervelocity impact RF/optical
measurements*, DOI `10.5281/zenodo.7939431`, by Kimia Fereydooni, Nicolas Lee,
and Sigrid Elschot. The immutable record explicitly declares CC BY 4.0.

The selected collection contains 21 direct `.trc` files totaling 30,007,565
source bytes. They provide seven synchronized detector channels for each of
three accelerator shots:

- three 315 MHz patch-antenna channels;
- three 916 MHz patch-antenna channels; and
- one photomultiplier optical channel.

The shots span impactor masses and velocities documented by the publisher:
3.51 fg at 23.9 km/s, 2.52 fg at 34 km/s, and 0.93 fg at 50.7 km/s. The
downloader revalidates record identity, title, license, exact file count and
aggregate bytes, and every Zenodo-provided MD5.

## Native representation

All 21 files contain valid LeCroy `WAVEDESC` descriptors with `COMM_TYPE=WORD`
and little-endian `COMM_ORDER=LOFIRST`. The strict standard-library parser
validates descriptor and block sizes, source bounds, signed-int16 waveform
counts, scale metadata, and subarray geometry. Every file contains exactly one
complete natural acquisition and ends exactly after its declared
`WAVE_ARRAY_1` payload.

Build removes only the 357-byte container prefix and copies `WAVE_ARRAY_1`
unchanged. Voltage gain, voltage offset, sampling interval, and instrument
model remain in the index; no physical scaling, filtering, clipping,
resampling, or byte-order conversion is applied.

## Verified output

The accepted family contains:

- 21 complete and byte-distinct samples;
- 15,000,034 signed-int16 values and 30,000,068 primary bytes;
- four observed lengths from 499,999 to 1,000,002 values; and
- three LeCroy instrument models across RF and optical channels.

The channels provide useful distribution diversity. The WS434 traces contain
92–166 distinct ADC codes and zlib-9 ratios from `0.355093` to `0.420985`.
WP7000 antenna traces contain roughly 3,500–4,000 distinct codes with ratios
near `0.79–0.81`. Photomultiplier traces contain up to 23,827 distinct codes
with ratios near `0.78`. Across the family the median zlib-9 ratio is
`0.783041`; none of the samples is constant or duplicated.

Build and verification pass. Verification rechecks all source MD5s and
container semantics, independently locates every waveform payload,
byte-compares all emitted samples, validates index fields and hashes, and
rejects missing or extra outputs.
