# LeConte Bay CHIRP SEG-Y Float32 Development — 2026-08-01

`zenodo_leconte_chirp_segy_f32` adds trace-structured marine subsurface
reflection amplitudes. It complements the existing 1D signed-int32 seismic
station windows and the float32 Martian SHARAD radargram with thousands of
natural Earth-based acoustic traces having multiple lengths.

## Source, selection, and license

Zenodo record `4008565`, *LeConte Bay CHIRP Subsurface Data*, declares CC BY
4.0 and DOI `10.5281/zenodo.4008565`. The accepted subset is the five smallest
qualifying files from that coherent record:

- `20170916063700utc_acrossfjord.jsf.sgy`
- `20170913032800_alongfjord.002.jsf.sgy`
- `20170912181500_alongfjord.001.jsf.sgy`
- `20170913032800_alongfjord.001.jsf.sgy`
- `20170918085900utc_acrossfjord.jsf.sgy`

Together they occupy 127,053,172 source bytes. Exact URLs, sizes, and Zenodo
MD5 checksums are pinned and enforced. The broader discovery examined 188
bounded direct SEG-Y files: 23 used IEEE-float32 format code 5, while the rest
used IBM float32, signed int32 in a nonstandard little-endian header, or other
non-target representations.

## Representation and natural samples

All five accepted files have standard big-endian SEG-Y headers, no extended
textual headers, and sample format code `5`, which is IEEE float32. One SEG-Y
trace is one natural output sample. The parser follows each trace header's
sample count, preserving source file order and trace order.

The only transformation reverses the four bytes of every source word from
SEG-Y big-endian order to corpus little-endian order. IEEE value bit patterns
are otherwise unchanged. No scaling, interpolation, resampling, clipping,
trace concatenation, or imputation is performed. Malformed headers,
truncation, trailing bytes, and non-finite samples are fatal.

## Realized and verified output

- primary samples: `6,895` traces
- primary values: `31,345,093` float32 amplitudes
- primary bytes: `125,380,372`
- observed trace lengths: `2,884`, `3,608`, `3,616`, `4,332`, `4,340`,
  `5,056`, `5,063`, `5,780`, and `6,504`
- observed value range: `[0.0, 2346.42578125]`

Verification rechecks every source size and MD5, rereads every indexed source
payload by exact byte offset, validates its SHA-256, performs the endian
normalization independently, and byte-compares it with the emitted sample.
All 6,895 traces and 125,380,372 bytes passed.
