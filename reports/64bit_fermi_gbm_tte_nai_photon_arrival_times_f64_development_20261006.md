# Fermi GBM burst TTE NaI photon arrival times float64 development

## Outcome

Accepted `fermi_gbm_tte_nai_photon_arrival_times_f64`. Each sample is the complete native `EVENTS.TIME` column of one Fermi Gamma-ray Burst Monitor burst time-tagged-event (TTE) file for one NaI(Tl) detector: the arrival time of every detected photon, in seconds relative to the burst trigger.

The arrival time is the measurement here. A TTE event list is a point process, and light curves, T90 and variability are all derived from the time tags. The accepted `dc_lidar_2015_gps_time_f64` already treats a native float64 per-event time tag as primary.

The local corpus has no gamma-ray photon event-time family at any width:
- the accepted NICER recipes emit PI and detector-address columns of X-ray event files, never TIME;
- `nasa_heasarc_batse_cont_counts_i16` emits binned counts.

## Source and rights

- **Source:** NASA HEASARC archive, anonymous S3 mirror `https://nasa-heasarc.s3.amazonaws.com/fermi/data/gbm/bursts/`, which mirrors `https://heasarc.gsfc.nasa.gov/FTP/fermi/data/gbm/bursts/`. Products are written by the GBM Instrument Operations Center (ORIGIN `GIOC`).
- **Population:** 4,178 burst directories for the complete years 2008–2025. 2026 is excluded because it is still growing.
- **Selection:** 60 targets at `floor((k+0.5)·4178/60)`, stepping t, t+1, t−1, … when a burst does not qualify. 58 targets took their first candidate:
  - `bn090626707` was skipped because its largest NaI TTE file holds only 46,121 events;
  - `bn110318552` was skipped because its window starts at −644.5 s.
- **Detector rule:** the largest highest-version NaI TTE file of each burst. This partly tracks detector background; realized detectors are na 12, n5 9, n7 9, n3 8, n8 6, nb 5, n1 4, n4 3, n9 3, n2 1.
- **Pinning:** `sources.tsv` (SHA-256 `21281129d01cda224d186720645462af6eae42d8c1374ff5b2dfea43855864bf`) pins key, exact size, S3 ETag, NAXIS2 and TZERO1. ETags are 46 single-part MD5s and 14 composite multipart ETags with 8 MiB parts.
- **Download:** 452,992,320 bytes in 60 FITS files. FITS CHECKSUM and DATASUM verified in all 4 HDUs of every file.
- **License:** NASA SMD Scientific Information Policy (`LicenseRef-NASA-SMD-Open-Data`):
  - SMD policy: "NASA holds this information, including publications, data, and software, as a public trust …", and SMD policy is that research information "be made publicly available".
  - Fermi FSSC data policy: "GBM data were not proprietary at any time during the mission and are released as early as possible during science operations."
  - NASA media guidelines: NASA content is "generally not subject to copyright in the United States". The AI-use conditions (no insignia in training, no attribution of output to NASA, no implied endorsement) are recorded in `[safety].usage_notes`.
  - Same basis as the accepted BATSE and NICER HEASARC recipes.

## Shape and conversion

- **Natural record:** one burst TTE file for one NaI detector (`glg_tte_<det>_bn<YYMMDDFFF>_vNN.fit`). The whole EVENTS.TIME column becomes one sample. Nothing is concatenated, split or tiled.
- **Field:** FITS BINTABLE `EVENTS`, `TIME` `1D` (big-endian IEEE-754 float64, `TUNIT 's'`, `TZERO1 = TRIGTIME`, no TSCAL or TNULL). The stored doubles are byte-swapped to little-endian, bit-exact, in source row order. TZERO1 is recorded in the index only.
- **Not emitted:** PHA (int16 channel), EBOUNDS and GTI.
- **Stored-value structure (judge finding):**
  - Stored values are exact multiples of ulp(MET): 2⁻²⁵ s for 2008 to mid-2009, 2⁻²⁴ s to 2017, 2⁻²³ s after. In little-endian byte order the two lowest mantissa bytes are always zero.
  - `stored + TZERO1` lies on the 2 µs GBM clock lattice; the largest residual is 0.054 tick.
  - **Correction to the recipe README and manifest:** they say adding TZERO1 would "round information away". It would not: `stored + TZERO1` is exact in float64, because the stored values were already quantized when ground processing subtracted TRIGTIME. Emitting the stored field remains correct as the native, unrecomputed column.
- **Ordering:**
  - 58 files are non-decreasing throughout.
  - `bn090629543` (n3, row 235,054): one backward step of 0.098926 s. A 74-event run fills the 51.5 ms hole that precedes the overlapped events.
  - `bn111018785` (n7, row 30,195): one backward step of 0.098418 s. A 138-event run sits beside a 100 ms hole at −1.309 s.
  - Neither run is a shifted copy: offsets are not constant and PHA sequences differ. Both are kept as stored. Build and verify tolerate at most 4 steps of at most 1 s per file.
  - There are 189 same-tick consecutive ties across the dataset.
- **Eras:** two ground-processing eras differ only in window length:
  - 15 files (2008–2012, `GBM_TTE_Reader.pl`) cover about −24…−35 s to +300 s;
  - 45 files (2013–2025, `make_trigger_TTE_file` / `MakeTriggerTte`) cover about −131…−139 s to +475…+482 s;
  - four post-2012 files have shorter natural windows, ending at +32.7, +62.3, +283.8 and +401.4 s.

## Accepted output

- Primary series: `gbm_nai_tte_photon_time_f64` (float64, little-endian, native_numeric)
- Primary samples: 60
- Primary values: 45,118,967
- Primary bytes: 360,951,736
- Minimum sample: 205,859 values (`bn201223173`)
- Median sample: 773,682.5 values
- Maximum sample: 2,726,534 values (`bn140801792`)
- Global value range: −138.75215 s to +482.31450 s
- Equal consecutive times: 189; backward steps: 2, in 2 files
- Median event rate: 1,081–4,277 events/s per file. Burst peaks reach 2.1–9.6× the median in several files.
- Generic compressibility of the first 4 MB: zlib-9 2.25–2.62×, xz-6 3.39–3.40×

## Judge checks

- **Gate:** `gate.py` PASS with no warnings (values 45,118,967; bytes 360,951,736; 60 samples; median 773,682.5; widths [64]).
- **verify.sh:** re-run by the judge, `verify ok`. It is an independent parser with its own DATASUM check and byte equality against every source column. build.sh, gbm_tte.py and verify_tte.py contain no network calls.
- **Download log:** 60/60 files validated with `checksums=4 datasums=4`; `download_inventory=ok bytes=452992320 rows=45118967`. The sources.tsv SHA-256 matches the manifest.
- **Bytes:** inspected with struct and exact `fractions.Fraction` arithmetic on 9 samples spanning 2008–2025, plus rate curves of all 60:
  - Δt values are multiples of 2 µs;
  - the absolute lattice and ulp(MET) quantization are as described above;
  - minimum Δt is about 2 µs;
  - all 60 sample hashes are unique;
  - the backstep runs were analysed against the source PHA columns.
- **Rights:** re-opened the SMD policy page and the NASA media guidelines (AI section), and read the downloaded FSSC policy copy. The basis matches three accepted HEASARC recipes. No credentials; no personal data.
- **Novelty:** `novelty.py` with both GBM URLs and the distinctive terms found no Fermi, GBM or photon-event-time match in recipes, registry, ledger or downstream. The only overlap is the shared host with the NICER, BATSE and SDO recipes, which take different fields. Labelled `new_quantity`.
- **Homogeneity and volume:** one instrument, unit, lattice and pipeline. The eras differ only in window length. 60 natural records of 1.6–21.8 MB each, against a population of 4,178 bursts × 12 NaI detectors.
