# Fermi GBM Burst TTE NaI Photon Arrival Times (float64)

`fermi_gbm_tte_nai_photon_arrival_times_f64` collects the native float64
photon arrival times recorded by the Fermi Gamma-ray Burst Monitor (GBM)
around gamma-ray-burst triggers. Each sample is the complete `EVENTS.TIME`
column of one burst's time-tagged-event (TTE) file for one NaI(Tl) detector,
emitted bit-exact as little-endian float64. There are 60 samples, one per
burst, evenly spaced over 2008-07 to 2025-12: 45,118,967 values and
360,951,736 bytes.

## What the numbers are

GBM's TTE mode tags every detected photon (or charged-particle event) with
its arrival time on a 2 µs clock and a 128-channel pulse-height code. The
burst TTE files `glg_tte_<det>_bn<YYMMDDFFF>_vNN.fit` hold that event list for
a window around the trigger. Each NaI file is a FITS binary table `EVENTS`
with two columns:

| column | TFORM | meaning |
| --- | --- | --- |
| `TIME` | `1D` (float64), `TUNIT 's'`, `TZERO1 = TRIGTIME` | photon arrival time |
| `PHA` | `1I` (int16) | pulse-height channel 0..127 |

**The arrival time is the measured quantity here, not a timestamp attached to
some other measurement.** A TTE event list is a point process: the instrument
measures *when* each photon arrived. Light curves, burst durations (T90),
pulse structure and variability timescales are all derived from the time
tags. So the TIME column is the primary physical observable of this product,
and it is collected as the primary series. The repository already accepts
this framing: `dc_lidar_2015_gps_time_f64` collects the native float64
per-return GPS time of airborne-LiDAR point records as its primary series.
Here the column is even more central, because the event rate structure in
time *is* the gamma-ray-burst signal.

The PHA column (a 16-bit channel code), the EBOUNDS calibration table, the
GTI table and the header times are **not** emitted as series. PHA is not a
64-bit quantity.

### Stored values vs. TZERO

The FITS column declares `TZERO1 = TRIGTIME`, so the physical absolute time
in Fermi mission elapsed time (MET, seconds since 2001-01-01 TT) is
`stored + TZERO1`. The recipe emits the **stored** doubles unchanged, which
are seconds relative to the trigger, -138.8 s to +482.3 s in the pinned
headers. It does not add TZERO1:

- adding it in float64 would round information away (ulp ≈ 1.2e-7 s at
  MET ≈ 6e8 s) and turn a native field into a local recomputation;
- the stored relative value is what the GBM pipeline actually writes, and
  what GBM analysis tools work with.

`TZERO1` (= `TRIGTIME`), `TSTART`/`TSTOP` relative to the trigger, and the
GTI intervals are kept per sample as index or ingest metadata only. The GTI
intervals are stored values with their own TZERO, also equal to TRIGTIME
in the probed files. The header probes show that `stored + TZERO1` lies on the 2 µs clock
lattice to within double rounding, in both processing eras.

## Selection

`discover.sh` (documentation, not part of the download contract) lists the
anonymous `nasa-heasarc` S3 mirror of
`https://heasarc.gsfc.nasa.gov/FTP/fermi/data/gbm/bursts/`. It lists the year
prefixes, then every year's burst directories with `delimiter=/` and keyset
pagination (pages hold 1000 keys). It then runs `scripts/select_bursts.py`:

- **Population**: the 4,178 burst directories of the complete years
  2008-2025, sorted by burst name, which is chronological. 2026 (210
  directories on 2026-10-06) is still growing and is excluded.
- **Targets**: `t_k = floor((k + 0.5) * 4178 / 60)` for k = 0..59. Each target
  tries indices t, t+1, t-1, t+2, ... and takes the first burst that
  qualifies.
- **Files**: only uncompressed NaI TTE files
  `current/glg_tte_n[0-9ab]_<burst>_vNN.fit`. The highest `vNN` per detector
  is used. BGO (`b0`, `b1`), CTIME and CSPEC products are never considered.
- **Detector rule** (deterministic from the pinned listing): the NaI file
  with the largest S3 `Size`, ties going to the lowest detector index. That
  is the detector that recorded the most events in the TTE window. This is
  burst plus background, so it is often, but not always, the burst-facing
  detector. Realized detectors: na 12, n5 9, n7 9, n3 8, n8 6, nb 5, n1 4,
  n4 3, n9 3, n2 1.
- **Header probe** (40 KiB range GET): PRIMARY/EVENTS identity and schema,
  `NAXIS2 >= 100,000`, and a `TSTART`/`TSTOP` window within -400..0 s and
  0..2000 s of `TRIGTIME`. The EVENTS data unit must also fit inside the
  listed object.

58 targets landed on their first candidate. Two were skipped deterministically:

- `bn090626707`: its largest NaI TTE file holds only 46,121 events (a
  truncated TTE window). The target took `bn090629543` instead.
- `bn110318552`: its TTE window starts at -644.5 s, outside the sanity bound.
  The target took `bn110319628` instead.

`sources.tsv` pins burst, year, detector, version, key, exact size, S3 ETag,
NAXIS2, TZERO1 (as `repr`), the TSTART/TSTOP window, the population index
and the target index.

## Download, build, verify

```bash
bash staging/fermi_gbm_tte_nai_photon_arrival_times_f64/download.sh   # ~453 MB, 60 files
bash staging/fermi_gbm_tte_nai_photon_arrival_times_f64/build.sh
bash staging/fermi_gbm_tte_nai_photon_arrival_times_f64/verify.sh
```

All three honour `DATA_DIR` (default `.data`) and log to
`$DATA_DIR/logs/fermi_gbm_tte_nai_photon_arrival_times_f64/`.

- **download.sh** uses resumable curl (`-C -`, `--speed-limit 1024
  --speed-time 120`, no `--max-time` on payloads) into `.part` files and
  renames a file only after `scripts/validate_download.py` accepts it:
  - exact size and exact S3 ETag (content MD5, or the 8 MiB-part composite
    MD5 `-N` for the 14 objects over 8 MiB);
  - FITS identity (`TELESCOP GLAST`, `INSTRUME GBM`, `DATATYPE TTE`,
    `FILETYPE 'GBM PHOTON LIST'`, `DETNAM` matching the file's detector,
    `FILENAME`);
  - HDU sequence PRIMARY/EBOUNDS/EVENTS/GTI and the EVENTS schema;
  - **every present FITS `CHECKSUM`/`DATASUM`**, with both required on
    EVENTS (the GBM pipeline writes them in every HDU);
  - zero padding, no trailing bytes, and the pinned NAXIS2 and TZERO1.

  It also fetches the FSSC data-policy page as soft provenance.
- **build.sh** (`scripts/gbm_tte.py`) re-walks each file by EXTNAME and
  writes `EVENTS.TIME` as little-endian float64. One sample per file:
  `samples/<id>/gbm_nai_tte_photon_time_f64/<burst>_<det>_vNN_time.bin`. It
  then requires:
  - finite times, kept in stored row order with at most 4 decreasing steps
    per file of at most 1 s each (see *Source order* below);
  - PHA within 0..127 (a row-alignment check);
  - min <= first time in [-400, 0) s and last time <= max in (0, 2000] s;
  - at least 10,000 value changes between consecutive events, and unique
    outputs.

  It writes `index/<id>/samples.jsonl` with the standard fields plus burst,
  detector, TZERO1, window, first/last/min/max, equal-step and backstep
  counts, the largest backstep, the smallest positive step and SHA-256.
- **verify.sh** (`scripts/verify_tte.py`) is an independent implementation
  with its own card parser, TFORM-derived column offsets and its own EVENTS
  `DATASUM` check. It unpacks with `struct.iter_unpack('>dh')` and repacks
  `'<d'`, then checks:
  - byte equality with every emitted sample;
  - the same ordering tolerance, span and degeneracy rules;
  - every index statistic, the exact sample inventory and the manifest
    totals.

Parsers were self-tested before download on synthetic GBM-like FITS files
with valid CHECKSUM/DATASUM cards, and re-run after the backstep policy
change. The output was bit-exact. Both the build and the independent
verifier:

- rejected a flipped data byte (DATASUM), a `1E` TIME column, an
  out-of-range PHA, 6 backsteps in one file and a single 2 s backstep;
- tolerated and recorded a single small backstep identically.

The build also rejected a wrong DETNAM, and the verifier rejected a tampered
sample. The real-file header layout,
checksum convention and row decoding were confirmed on range-GET probes of
2008, 2020 and all 60 selected files.

## Homogeneity

All 60 samples share one instrument (GBM NaI(Tl)), one quantity (photon
arrival time in seconds relative to the trigger), one 2 µs clock lattice and
one FITS layout (`TIME 1D` + `PHA 1I`, `NAXIS1 = 10`). The 2008-2025 span
covers two ground-processing eras that differ only in window length:

| era | creator | TTE window | samples | events per file |
| --- | --- | --- | --- | --- |
| 2008-2012 | `GBM_TTE_Reader.pl` v2.10-2.19 | -23.8..-34.5 s to +300.0..+300.5 s | 15 | 400k-584k, median 447k |
| 2013-2025 | `make_trigger_TTE_file` v1.2-1.3, then `MakeTriggerTte` v1.5.9-1.5.26 | -131.1..-138.8 s to +475..+482 s (41 of 45) | 45 | 206k-2.73M, median 798k |

The value domain, the precision and the generating process are the same in
both eras. To our understanding the longer window follows GBM's late-2012
move to continuous TTE, after which trigger files are cut from the
continuous stream on the ground. Window length and event rate vary with
brightness and background. That is natural content variation, not a regime
mix. Notable natural records:

- `bn140801792` (2,726,534 events) and `bn250207053` (2,327,337 events) have
  about 3x the typical event rate.
- Four post-2012 files have shorter TTE windows: `bn201223173` ends at
  +32.7 s, `bn140501139` at +62.3 s, `bn141118678` at +283.8 s and
  `bn231120016` at +401.4 s (header TSTOP).

All are kept as published.

### Source order

Times are emitted in stored row order and never sorted. 58 of the 60 files
are non-decreasing throughout. Two early-mission files each contain exactly
one backward step of about 0.099 s, where an interleaved run of events
overlaps the preceding 0.099 s. No row is an exact (TIME, PHA) duplicate.

| file | row | step | run | rate in overlap window |
| --- | --- | --- | --- | --- |
| `bn090629543` (n3) | 235,055 | 140.515814 → 140.416888 s | 74 events | combined ≈ neighbouring rate (1,334/s vs 1,417/s) |
| `bn111018785` (n7) | 30,196 | -1.110846 → -1.209264 s | 138 events | combined ≈ 2× neighbouring rate (2,632/s vs 1,347/s) |

These look like event packets written out of time order in the 2009-2011
ground processing. Sorting would alter the native column, and dropping
events would discard data, so both files are kept as stored. Build and
verify tolerate at most 4 such steps per file, each at most 1 s, and record
`backsteps` and `max_backstep_s` per sample. There are also 189 consecutive
equal times over the whole dataset (two events in the same clock tick); they
are legitimate and kept.

## Realized output

- 60 samples, 45,118,967 float64 values, 360,951,736 bytes.
- Median 773,682.5 values per sample; range 205,859 to 2,726,534.
- Global value range -138.75215 s to +482.31450 s.
- Every sample's SHA-256 is unique.
- Generic compressibility of the first 4 MB of three samples (2008, 2014,
  2020): zlib-9 2.2-2.6×, xz-6 3.3-3.4×. The material is non-trivial but
  highly structured: nearly monotone doubles on a 2 µs lattice.

## Novelty

`tools/autocollect/novelty.py --url .../fermi/data/gbm/bursts/ --terms fermi
gbm` finds no recipe, registry, ledger or downstream match. The only overlap
is the host shared with the NICER, SDO and BATSE HEASARC recipes, which use
different missions, files and fields. The NICER recipes collect PI (int16)
and detector addresses (uint8), not event times. The BATSE recipe collects
binned counts. The corpus has no gamma-ray event-time data at any width. The
nearest 64-bit relative is `dc_lidar_2015_gps_time_f64` (airborne LiDAR GPS
time), a different instrument and modality. Novelty kind: new quantity, a
high-energy photon-event point process at 64 bits.

## License

NASA SMD Open Scientific Data Policy (`LicenseRef-NASA-SMD-Open-Data`). These
quotes were re-read on 2026-10-06:

- SMD policy page: "NASA holds this information, including publications,
  data, and software, as a public trust to increase knowledge and serve the
  public good. It is Science Mission Directorate (SMD) policy … that
  information produced from SMD-funded scientific research activities be
  made publicly available."
- Fermi FSSC data policy: "GBM data were not proprietary at any time during
  the mission and are released as early as possible during science
  operations."
- NASA media guidelines: NASA content "generally are not subject to
  copyright in the United States". Their AI-applications section ("NASA is
  committed to transparency, open science, and making data available to
  everyone") forbids attributing AI output to NASA and using NASA insignia
  in AI training. Neither restriction touches these numeric samples.

This is the same basis as the accepted `nasa_heasarc_batse_cont_counts_i16`,
`nasa_heasarc_nicer_pi_i16` and `nasa_heasarc_nicer_detector_u8`. Citation:
Meegan et al. 2009, ApJ 702, 791, plus HEASARC/FSSC acknowledgement.

## Caveats

- The detector rule favours the busiest NaI detector. Background differences
  between detectors (na appears 12 times) influence the choice as much as
  burst geometry does.
- Times are relative to each burst's own trigger. Samples share the value
  domain, but their absolute epochs are only in the metadata.
- The 1-GB cap is not approached: the 361 MB of primary output was chosen as
  60 samples (well past the 50-sample guidance), not sized to the cap. The
  full archive is about 4,178 bursts × 12 NaI files.
