# OscGrid power-grid oscillogram int16 development

## Outcome

Accepted `figshare_oscgrid_comtrade_raw_adc_i16` from the pinned OscGrid labeled raw COMTRADE archive (figshare article 28465427, version 6).

This is a new modality for the corpus: point-on-wave voltage and current waveforms recorded by relay-protection and automation terminals in operating 0.4–35 kV substations. The nearest local families hold PMU phasor magnitudes at 50 frames/s (`zenodo_gridgnosis_pmu_voltage_magnitude_f32`), 10 Hz grid frequency (`fingrid_nordic_grid_frequency_10hz_f32`) and minute-level household aggregates (`household_power_uci`). The downstream `power_voltage` family is the UCI household-power minute-averaged voltage column, not waveforms. The recipe meets the retry conditions of the blocked `zenodo_comtrade_i16` and `zenodo_comtrade_power_fault_i16`.

## Source and rights

- Source: figshare file 60073955, `Labeled_raw_v1.1.7z`
- Compressed bytes: 94,882,365
- Published MD5: `5e15133fd38bf131115897b8737cbf19`
- SHA-256: `33a9fae8e21446b40a3099e6ffa733b679af4f3df4d4ce90aa4b06aeddf45ff8`
- License: CC BY 4.0

The figshare API record for article 28465427 v6 returns license `{'name': 'CC BY 4.0', 'url': 'https://creativecommons.org/licenses/by/4.0/'}` and lists the exact file with a matching computed MD5. `download.sh` re-checks the license, embargo state and file entry on every run. The Scientific Data descriptor (doi 10.1038/s41597-026-06587-8) is CC BY-NC-ND and is only cited. The authors' MIT-licensed converter is not used. Recordings are anonymized: placeholder dates and hash file names, with no site or operator identity.

## Shape and conversion

Each natural record is one COMTRADE-1999 cfg/dat oscillogram. The archive is decoded by a narrow pure-stdlib 7z reader. It handles the LZMA-encoded header and one LZMA1 solid folder of 585,730,365 bytes, and checks the CRC32 of all 960 members. Because cfg and dat members are not adjacent in the stream, the folder is decoded twice.

A record is kept only if all of the following hold:
- rev 1999, ASCII, 50 Hz, a single 1600 Hz rate, timemult 1
- int16 code domain declared on every analog channel
- exact row count, sample numbers 1..N, timestamps exactly (n−1)·625 µs
- every analog token finite, within 1e-6 of an integer (float-export artifacts reach at most 5.5e-12) and inside the cfg min/max

Each oscillogram yields two samples, one per series. Each holds the standardized whitelisted channels of that type in cfg order, channel-major `[channels, endsamp]`, as little-endian int16 sample codes. The codes are unscaled; the cfg defines secondary value = a·code + b.

Channel selection:
- **Voltage:** `U | BusBar|CableLine-n | phase: A/B/C/N/AB/BC/CA` (V) with a within ±15% of 0.016 V/code.
- **Current:** `I | Bus-n | phase: A/B/C/N` (A) with a within ±15% of 0.0092 A/code.
- **Excluded and counted:**
  - 17 Rogowski `I_raw` (di/dt) channels
  - 12 relay-computed dif/braking per-unit channels
  - 12 voltage and 12 current channels from one terminal type on another input range
  - 6 sensitive earth-fault inputs (0.0024 A/code)
  - all digital and MLsignal channels

Index rows carry each channel's name, unit, a, b, skew, min/max, ratio and P/S flag.

## Accepted output

- Records in archive: 480
- Records dropped:
  - 6 rev-2013
  - 1 BINARY
  - 3 cfgs declaring 0..0 ranges
  - 1 with −32768 below a declared −32767 floor
- Records emitted: 467. 5 parsed records have no voltage sample and 5 have no current sample.

| Series | Samples | Channels | Values | Bytes | Values per sample (min / median / max) | Code range |
|---|---|---|---|---|---|---|
| `oscgrid_voltage_codes_i16` | 464 | 4,406 | 48,719,331 | 97,438,662 | 8,000 / 83,200 / 683,200 | −28,126..26,831 |
| `oscgrid_current_codes_i16` | 464 | 2,125 | 23,310,621 | 46,621,242 | 9,372 / 41,600 / 292,800 | −24,560..24,270 |
| Total primary | 928 | 6,531 | 72,029,952 | 144,059,904 | median 62,400 | |

- Kept scale bands: 0.014684–0.016912 V/code and 0.009148–0.009298 A/code.
- There are no constant samples, no duplicate samples and no full-scale codes.
- 3,990,405 float-artifact tokens were rounded after the integrality check.

The local build and the independent byte-for-byte verification both completed successfully against the pinned archive.

## Judge checks

- **Gate:** `tools/autocollect/gate.py` passes with no warnings: 928 samples, 72,029,952 values, median 62,400, width 16.
- **Verify:** I re-ran `verify.sh` myself: exit 0 in 48 s. Both hashes matched, all 928 samples were re-derived and byte-compared by an independent float() parser, and the drop set matched.
- **Independent decode:**
  - I extracted two pairs (`e4e775cf…`, `904f4f1b…`) with `/usr/bin/bsdtar`.
  - My own minimal COMTRADE parser reproduced all four emitted samples byte for byte.
  - The per-channel `a` factors in the index match the cfg.
- **Bytes:**
  - 12 random samples inspected channel by channel. Phase-to-ground peaks are about 5,200 codes (≈83 V secondary), line-to-line about 9,000, and N is small and measured: 849 of 850 N channels are not A+B+C.
  - Lag-16 autocorrelation −1.00 and lag-32 +1.00: 50 Hz at 1600 Hz.
  - gcd is 1 and about 50% of codes are odd: full lattice, no widening.
  - No duplicate channels within samples or across samples, and no repeated 128-value windows across records.
  - Near-silent tail: 29 current samples (5.4% of current bytes) and 8 voltage samples (2.5%) peak at ≤4 codes. These are real de-energized recordings, so they are acceptable.
  - Median order-0 entropy is 11.9 bits (V) and 6.3 bits (I).
- **Homogeneity:** a full cfg pass tabulated `a` over all whitelisted channels. The kept clusters (0.0147–0.0169 V/code; 0.0091–0.0093 A/code) are separated from the excluded regimes (1.6e-5 V/code; 3.06e-4 and 0.0024 A/code) by two to three orders of magnitude, so the band rule isolates distinct input regimes and does not tailor a cut. P/S = S on every kept channel.
- **Rights:** I fetched the figshare API record myself: CC BY 4.0, not embargoed, exact file and MD5 listed. No credentials appear in any script, and there is no personal data.
- **Novelty:** `novelty.py` URL and term searches turned up no oscillogram or COMTRADE family locally or downstream. I traced downstream `power_voltage` (`repro/commands/power_reshard_num16.py`) to UCI household-power minute voltage, which is a different material.
- **Non-blocking notes:**
  - One terminal calibration signature accounts for 283 of 464 records; there are 51 signatures in all.
  - The manifest origin note says the article has 41 files; the live record now lists 42. This does not affect the pinned file.
