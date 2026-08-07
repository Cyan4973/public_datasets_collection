# Open Ephys extracellular-voltage int16 development — 2026-08-06

## Outcome

Accepted `zenodo_open_ephys_continuous_i16`, four native signed-int16
extracellular neural-voltage streams from Zenodo record `20726062`,
*SpikeInterface Training Dataset*, DOI `10.5281/zenodo.20726062`, released
under CC BY 4.0.

## Domain and shape distinction

This family contributes dense continuous extracellular ADC signals. It is
materially different from the accepted Neuropixels float32 family, which
contains sparse derived 61-sample spike templates, and from scalp EEG or ECG
features. Each output is one complete electrode-channel time series containing
66,593,792 samples at 30 kHz, approximately 37 minutes of recording.

The source exposes 16 numbered neural channels. To bound acquisition and avoid
post-analysis cherry-picking, CH1, CH6, CH11, and CH16 were selected before
full-family analysis as a deterministic spread through channel-number order.
ADC and nearly constant AUX streams are semantically different and excluded.

## Source and decoding

The selected session is a mouse running in an open field, recorded with
tetrodes aimed at medial entorhinal cortex. Its 2.16 GB ZIP archive is pinned
by exact size and MD5; only the four selected compressed members are
range-extracted.

Every member is legacy Open Ephys v0.4 with a 1,024-byte ASCII header and
65,033 fixed records. Every record contains a little-endian timestamp, sample
count and recording number, followed by 1,024 big-endian signed-int16 sample
words and the standard ten-byte marker. All 260,132 records have valid counts
and markers. Timestamps advance continuously by exactly 1,024 samples on all
four synchronized channels.

The focused byte-order preflight found a sampled median adjacent step of 188
under the documented big-endian interpretation versus 19,200 byte-swapped.

## Accepted material

- 4 complete synchronized electrode-channel streams
- 65,033 records and 66,593,792 samples per channel
- 266,375,168 signed-int16 values
- 532,750,336 numeric bytes
- all four channel payloads unique
- all 260,132 record-block payloads unique within and across channels
- no constant blocks
- global value range -32,767 through 32,767
- 65,534 distinct values globally
- at least 24 distinct values and 27 transitions in every 1,024-sample block
- 138,005 zeros, about 0.0518% of values
- zlib-9 ratios approximately 0.788 through 0.854, median about 0.816

The decoder removes structural framing and concatenates only the source-order
big-endian sample words. Independent verification reparses every source record
and checks each emitted payload hash and inventory entry.

## License and safety

The exact record declares CC BY 4.0 and names Alessio Paolo Buccino and Chris
Halcrow as creators. Its description explicitly identifies the selected
session as a mouse recording. Only electrode voltage codes are emitted; event,
behavioral, positional, ADC, and AUX data are excluded. No human or personal
data is present.
