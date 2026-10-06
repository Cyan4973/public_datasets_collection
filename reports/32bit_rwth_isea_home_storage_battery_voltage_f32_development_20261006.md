# RWTH ISEA home-storage battery pack voltage float32 development

## Outcome

Accepted `rwth_isea_home_storage_battery_voltage_f32`.

Each sample is one complete calendar month of the 1 Hz battery pack terminal voltage (`V_in_V`, volts) of one privately operated residential PV home storage system in Germany. ISEA/CARL at RWTH Aachen University measured these systems from 2015 to 2022 (Figgener et al., Nature Energy 2024).

Novelty: this is the first battery-voltage family at 32 bits. Battery terminal voltage already exists in the local corpus at 64 bits as `kollmeyer_panasonic18650pf_drive_cycle_voltage_f64`, which holds lab single-cell drive cycles at 0.1 s on a Digatron cycler from Mendeley data. This recipe is a different upstream source and measurement setting: field-logged multi-cell packs at 1 Hz. It is therefore labelled `new_source`, not `new_quantity`. The other local battery family, `zenodo_battery_eis_complex_f32`, holds impedance spectra.

## Source and rights

- Source: Zenodo record 12091223, "Data for: Multi-year field measurements of home storage systems and their use in capacity estimation". Authors: Figgener, Haberschusz, Wessels, Kairies, Bors, van Ouwerkerk, Sauer. DOI 10.5281/zenodo.12091223. Companion article: Nature Energy, DOI 10.1038/s41560-024-01620-9.
- License: CC BY 4.0. The record metadata license id is `cc-by-4.0`, confirmed by a live API probe on 2026-10-06. It covers the deposit that contains every `Data_ID_*.zip` archive and `Metadata_and_Code.zip`. `download.sh` re-checks the license id, the title, and each archive's size and MD5 on every run.
- Acquisition: the per-system zips are 0.33-2.15 GB, so only the 36 selected members are fetched, by exact HTTP byte range. Each response must be a 206 with the exact `Content-Range`. The PK local header must match the pinned name, method, CRC32 and sizes, and the member is inflated in full with CRC32, size and end-of-stream checks.
  - Member spans: 806,046,462 bytes.
  - `Metadata_and_Code.zip`: 31,123 bytes, MD5 `23720da306f63fd2fd20fdc1a7b8f106`.
  - Download directory after pruning: 806,098,276 bytes.
- Safety: systems are numeric IDs and manufacturers are letters. No location or owner data is published or emitted, and only pack voltage is kept.

## Shape and conversion

- Natural record: one system-month CSV member, e.g. `07/2016_08_System_ID_07.csv`, with columns `Time,P_in_W,V_in_V,I_in_A,T_Bat_in_C,T_Room_in_C,Interpolated`. Its `V_in_V` column becomes one sample, in file order. Nothing is concatenated.
- Conversion: each decimal token goes through `float()` and is packed `<f` as raw little-endian float32, with no header. Logged tokens have at most six significant digits, and build and verify both check that they round-trip exactly. The 3,664 interpolated tokens with more than six significant digits are rounded to the nearest float32.
- Scope: 12 systems × 3 months spread over each system's record and the seasons.

| Manufacturer | Chemistry | Configuration | Nominal voltage | Systems |
|---|---|---|---|---|
| B | NMC | 13s | 46.8/48.1 V | 7-10 |
| C | NMC | 14s | 50.4 V | 11-12 |
| E | LFP | 16s | 51.2 V | 14-16 |
| E | LFP | 14s | 46.0 V | 19-21 |

- Exclusions:
  - Systems 1-6: 146.7 V scale.
  - Systems 13 and 17: 1 mV and 10 mV print lattices.
  - System 18: no complete month without disconnection readings.
- Missing-value policy, enforced by both build and verify:
  - exactly `days*86400` rows, every second once and in order;
  - `V_in_V` finite in [25, 65] V;
  - `Interpolated` in {0,1}, with at most 1% of rows set to 1;
  - at least half of logged tokens with six significant digits.
- Selection history: 12 candidate months failed (gaps, or disconnection readings of 0-0.14 V) and were replaced in a fixed order. Four passing extras were left unused. README and manifest both disclose this.

## Accepted output

- Primary samples: 36. Each system contributes 3 months.
- Primary values: 95,040,000.
- Primary bytes: 380,160,000.
- Sample size: minimum 2,419,200 values (February), median 2,678,400, maximum 2,678,400.
- Distinct values per sample: 9,494 to 117,403.
- Stored range: 42.5117 to 63.0447 V. All values share float32 exponent 132, i.e. lie in [32, 64).
- Interpolated rows: 4,712 in total. The maximum is 0.0399% of a month, and 11 of 36 months have none.
- Six-significant-digit share of logged tokens: 0.885 to 0.904.
- Years: 2015: 1, 2016: 7, 2017: 2, 2018: 4, 2019: 5, 2020: 7, 2021: 2, 2022: 8.

## Known characteristics (not disclosed in the recipe README)

- **Upstream sample-and-hold.** Rows are logged at 1 Hz, but many devices update more slowly. Effective update period (values ÷ changes):
  - 18 samples are true 1 Hz (1.00-1.07 s);
  - 11 samples are 1.25-2.42 s;
  - 7 samples are 3.0-6.2 s: system 08 at about 3.8 s, 10/2018-09 at 5.1 s, 19/2016-04 and 19/2017-12 at about 6.2 s.

  In the raw CSV of system 19, V, I and P each update about every 6 s, one second apart from each other, which looks like staggered register polling. The rate changes over time even within one system (07: 1.02 s in 2016, 1.72 s in 2022), so it is not a clean per-system regime.
- **Effective voltage quantum.** All systems print on the 0.1 mV grid, but the effective quantum differs: about 0.1 mV for systems 11, 12, 15 and 19-21; 0.3/0.4 mV steps for system 14; 0.2-0.6 mV for systems 7-10.
- **Ripple.** System 14 shows ±1 V ripple at about 60 A, aliased by 1 Hz sampling: 11k-70k one-second jumps above 1 V per month. This is genuine signal.
- **One glitch.** 21/2016-09 contains a single 63.0447 V reading at 27-Sep-2016 12:30:19, between readings of about 47.1 V, at I = 75 A. P stays at 2,853 W on that row, so it is a V-channel glitch. It is kept unedited.
- **Stale comment.** The `download.sh` header still says 39 members and about 878 MB; the real figures are 36 members and 806 MB.

## Judge checks

- **Gate:** `python3 tools/autocollect/gate.py staging/rwth_isea_home_storage_battery_voltage_f32` reports PASS with no warnings.
- **Verify:** I ran `bash staging/.../verify.sh` independently. It exited 0 (`verify_summary samples=36 systems=12 values=95040000 bytes=380160000 max_interp_share=0.0399%`) after byte-comparing all 36 re-derived samples and recomputing min/max from the stored float32 values.
- **Download:** `download.latest.log` (20261006_011935) shows `record_validation=ok`, `members_validated=36`, `span_bytes=806046462` and 8 stale spans pruned. The download directory holds exactly the 36 declared spans.
- **Locality:** `build.sh` reads only local files.
- **Bytes:** I decoded all 36 samples with `struct` and checked:
  - float32 exponent distribution;
  - distinct-value lattice steps;
  - run lengths and effective update period;
  - large one-second jumps and the glitch row;
  - cross-system independence (20/2016-09 vs 21/2016-09: r = 0.73, equal fraction 7.6e-5).

  I also read raw CSV rows from the member spans to confirm the hold pattern and the 63.04 V row are upstream.
- **Rights:** a live probe of the Zenodo API returned license `cc-by-4.0` for record 12091223. There are no credentials in any script.
- **Novelty:** `novelty.py` with `--url https://zenodo.org/records/12091223` (and the DOI URL) and terms `"home storage" figgener isea "battery voltage" "pack voltage" 12091223 V_in_V rwth home-storage` matched only this candidate, the generic Zenodo host, and a spurious `isea` hit. There are no registry, ledger or downstream matches.
- **Homogeneity:** one quantity, unit, float exponent, 0.1 mV print grid, campaign and 1 Hz logging. The remaining variation (chemistry bands, sensor quantum, upstream update rate) is natural device variation across stations of one quantity, recorded above.
