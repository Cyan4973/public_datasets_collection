# OscGrid labeled power-grid oscillograms: COMTRADE int16 voltage and current codes

This recipe collects point-on-wave oscillograms from relay-protection and
automation (RPA) terminals in operating 0.4-35 kV substations. The source is
the labeled subset of OscGrid (Evdakov et al., figshare article 28465427,
CC BY 4.0): 480 oscillograms, all on a 50 Hz grid and sampled at 1600 Hz. The
recordings cover normal operation, fast automatic bus transfer (FABT)
switching, motor starts, single-phase ground faults, voltage dips and short
circuits. Each one is a COMTRADE cfg/dat pair.

Each analog channel in the cfg declares an int16 code domain (min -32768 or
-32767, max 32767) and a linear scale `a * code + b` to secondary volts or
amperes. The recipe emits those declared sample codes unscaled. Per
oscillogram it writes two samples:

- `oscgrid_voltage_codes_i16`: the standardized voltage-transformer channels
  (`U | BusBar-n | phase: X`, `U | CableLine-n | phase: X`; phase-to-ground,
  residual N, and line-to-line), channel-major `[channels, endsamp]`.
- `oscgrid_current_codes_i16`: the standardized current-transformer channels
  (`I | Bus-n | phase: A/B/C/N`), channel-major `[channels, endsamp]`.

Each index row records the channel names and units, and per channel the cfg
`a`, `b`, skew, min/max, primary/secondary ratio and P/S flag.

## Why this is in scope

- New modality for the corpus. The local power-grid recipes hold PMU phasor
  magnitudes at 50 frames/s, grid frequency, and household energy aggregates.
  None of them holds raw point-on-wave voltage and current waveforms.
  `novelty.py` found no oscillogram or COMTRADE recipe, locally or downstream.
  Two earlier COMTRADE attempts (`zenodo_comtrade_i16`,
  `zenodo_comtrade_power_fault_i16`) were blocked because no permissively
  licensed source exposing matched cfg/dat pairs was known. This archive is
  such a source.
- License: the figshare record's API `license` field reads CC BY 4.0.
  `download.sh` re-checks it on every run. The Scientific Data descriptor
  article is CC BY-NC-ND and is only cited.

## Conversion details and caveats

- Container: `Labeled_raw_v1.1.7z` (94,882,365 B, MD5
  `5e15133fd38bf131115897b8737cbf19`). `scripts/sevenzip.py` is a narrow
  pure-stdlib 7z reader: encoded header, single-coder LZMA1/LZMA2 folders,
  SubStreamsInfo sizes and CRC32s, FilesInfo names. The solid block is
  decoded twice, because cfg and dat members are not adjacent: 232 dats
  precede their cfg and up to 138 MB would otherwise be buffered.
- Text artifacts: the publisher's ASCII export went through floating point,
  so some tokens read `3922.0000000000005` or `-1930.9999999999998`. Every
  analog token must lie within 1e-6 of an integer (the probe maximum was
  1.8e-12) and inside its channel's cfg min/max. Otherwise the whole record is
  dropped. Nothing is patched or clipped.
- Records outside the declared scope are dropped and listed in
  `filtered/<id>/ingest_stats.json`. These include rev-2013 FLOAT32 files
  (1 of the 61 cfgs probed), any rate other than 1600 Hz, and any non-int16
  code domain.
- Code-scaling homogeneity. A kept voltage channel's cfg factor `a` must lie
  within 15% of 0.016 V/code, the terminals' standard VT input (about ±540 V
  secondary full scale). A kept current channel's `a` must lie within 15% of
  0.0092 A/code, the standard CT input (about ±300 A). Kept channels end up at
  0.01468-0.01691 V/code and 0.009148-0.009298 A/code. One code therefore
  means about the same secondary voltage, or current, in every emitted
  channel.
- Channel exclusions, all counted in the stats:
  - `U_raw` / `I_raw` non-traditional sensors (17 channels). Rogowski coils
    output a voltage proportional to di/dt, so they measure a different
    quantity.
  - Relay-computed `I | dif-n` / `I | braking-n` per-unit channels (12).
  - Off-band input ranges (12 voltage, 18 current). One terminal type uses
    a = 1.6e-5 V/code and 3.06e-4 A/code, and some sensitive earth-fault
    current inputs use a = 0.0024 A/code.
  - Any non-standard analog name.
  - All digital channels, which include the expert `MLsignal_*` event labels.
- Some oscillograms are noise-dominated. A de-energized bus, for example,
  gives voltage codes of only a few counts. These are real recorder output and
  are kept. A series sample made entirely of one repeated value is not
  emitted; none occurred.
- "ADC" in the id reflects the cfg's int16 code declaration. The recipe makes
  no claim about the terminals' physical converter resolution.

## Realized output (2026-10-06 build)

| | voltage | current |
|---|---|---|
| samples (oscillograms) | 464 | 464 |
| channels | 4,406 | 2,125 |
| values | 48,719,331 | 23,310,621 |
| bytes | 97,438,662 | 46,621,242 |
| values per sample | 8,000-683,200 (median 83,200) | 9,372-292,800 (median 41,600) |
| code range | -28,126..26,831 | -24,560..24,270 |
| median sample peak | 5,277 codes (~87 V secondary) | 142 codes (~1.3 A secondary) |
| samples peaking below 64 codes | 20 (4.2% of bytes) | 120 (34% of bytes) |

- Records: 480 in the archive, 11 dropped, 467 emitted.
  - 6 drops are rev 2013.
  - 1 is a BINARY dat.
  - 3 have cfgs declaring code range 0..0 on every channel.
  - 1 has a -32768 code below its declared -32767 floor.
  - The other 2 parsed records have only off-band channels.
- Coverage gaps: 5 parsed records have no voltage sample and 5 have no
  current sample. There are no constant samples, no duplicate samples, and no
  full-scale codes.
- Integrality: 3,990,405 analog tokens carried float round-trip artifacts. The
  largest deviation from an integer was 5.5e-12.
- Waveform check: kept voltage channels show a 32-sample period, which is
  50 Hz at 1600 Hz.
- Light loads: many feeders carry little current, so the current series is
  low-amplitude but non-degenerate (median 270 distinct codes per sample).
  Those samples are kept as recorded.

## Run

```bash
bash staging/figshare_oscgrid_comtrade_raw_adc_i16/download.sh
bash staging/figshare_oscgrid_comtrade_raw_adc_i16/build.sh
bash staging/figshare_oscgrid_comtrade_raw_adc_i16/verify.sh
```

`verify.sh` re-decodes the archive and re-parses every dat with an independent
`float()`-based column parser. It requires the same drop set as the build,
byte-compares every sample, and checks the index metadata and manifest totals.
Logs go to `.data/logs/figshare_oscgrid_comtrade_raw_adc_i16/`.
