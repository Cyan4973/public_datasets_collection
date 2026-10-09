# Cassini RPWS WBR 10-kHz-mode Ex-dipole waveforms (uint8)

Raw 8-bit waveform data numbers from the Cassini Radio and Plasma Wave Science
(RPWS) Wideband Receiver, 10-kHz baseband mode (0.06-10.5 kHz, 36 us
sampling), Ex electric dipole, during the Saturn tour. These are the
audio-band plasma-wave and radio-emission waveforms behind the "sounds of
Saturn" (chorus, hiss, electron-cyclotron harmonics, plasma-frequency tones,
lightning whistlers, dust impacts).

- Source: NASA PDS Planetary Plasma Interactions Node, University of Iowa
  subnode, data set `CO-V/E/J/S/SS-RPWS-2-REFDR-WBRFULL-V1.0`,
  <https://space.physics.uiowa.edu/pds/CORPWS_nnnn/DATA/RPWS_WIDEBAND_FULL/>.
- License: NASA SMD open scientific data policy (public NASA PDS data); the
  volume README only asks users to acknowledge the PDS and the instrument PI.
- Natural record: one archived hourly WBR full-resolution product
  `T<yyyyddd>_<hh>_10KHZ<n>_WBRFR.DAT`. Each product is a fixed-length binary
  table; each record is one AGC-ranged waveform capture (32-byte big-endian row
  prefix + up to RECORD_BYTES-32 samples, the first SAMPLES valid).
- Sample: the valid samples of every record with FREQUENCY_BAND 2 (10 kHz),
  ANTENNA 0 (Ex), WBR validity bit set and TIMEOUT/SUSPECT clear, in file
  order, written unchanged as `<product>.u8`.

## Selection (discover.py, pinned in sources.tsv)

12 Saturn-tour volumes spaced 18 apart (CORPWS_0040, 0058, ..., 0238; late
2004 to 2017). In each, the 10-kHz baseband products (band token exactly
`10KHZ`, which excludes `75KHZ`, `5KHZ`, `325KHZ` and every `nnnnKHZ`
frequency-translated HF product) whose DAT size is 1,000,000-8,000,000 bytes
are sorted by product id and 8 are taken at evenly spaced ranks; a pick whose
label fails the checks, or whose first 32 KB is not all band 2 or has no Ex
record, is replaced by the next product in rank order.

Realized pin: 88 products (8 from each of 11 volumes; CORPWS_0202 has no
10-kHz product in the size window), 2004-314 to 2017-045, 297,335,488 DAT
bytes + 522,796 label bytes + 57,379 evidence bytes. Three picks were replaced
(two Langmuir-probe-only products, one Ew-only product).

The digit after `KHZ` in the filename is the capture-length class (1, 2, 4,
6, 8 -> 1056, 2080, 4128, 6176, 8224-byte records), not the antenna; the antenna is
filtered per record.

## Scripts

- `discover.py` (author-time, curl only): resolves `sources.tsv`.
- `download.sh`: fetches evidence files (size+MD5 pinned) and each pinned
  LBL/DAT (size pinned, resumable), validates every label and walks every
  record before accepting a DAT; records SHA-256 in `download_plan.tsv`.
- `build.sh` -> `scripts/build.py`: emits samples, `index/<id>/samples.jsonl`
  and `filtered/<id>/ingest_stats.json`.
- `verify.sh` -> `scripts/verify.py`: independent record walk, byte-compares
  every sample, checks index fields, exclusion rule, non-degeneracy (no DN
  above 50% of a sample, >= 200 DN levels overall) and manifest totals.

## Realized output (build 2026-10-09)

88 samples, 284,050,336 uint8 values (median 2,476,032; range 947,472 to
7,668,432), 11 volumes, 0 products excluded. In the pinned files every record
was band 2 / Ex / unflagged, so the per-record filters dropped nothing (they
are kept as guards). Across samples, the most common DN holds 1.9-11.2% of a
sample, DN 0 + 255 at most 0.65%, distinct levels 30-256, order-0 entropy
3.9-6.4 bits. `zlsim.py gate`: verdict OK, own ratio 2.83. The nearest family
is downstream MIT-BIH ECG `mitbih_mlii_u8` (distance 0.0298, loss 0.0349, just
over the 0.03 loss threshold). The next nearest are `mitbih_v2_u8` (0.0449 /
0.035) and `mitbih_v1_u8` (0.0538 / 0.0203). Both are 8-bit
biomedical waveforms, so the breadth margin is thin.

## Caveats

- GAIN (0-70 dB, chosen per capture by the onboard AGC) is not applied; the
  DN stream is the receiver-native regime. Gaps between captures are not
  represented (captures are concatenated in file order within one product).
- Labels declare `ITEMS` = a nominal value; the per-record SAMPLES field is
  authoritative and is what is used.
