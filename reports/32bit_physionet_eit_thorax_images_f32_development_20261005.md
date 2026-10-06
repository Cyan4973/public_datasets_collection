# PhysioNet PulmoVista thoracic EIT image sequences float32 development

## Outcome

Accepted `physionet_eit_thorax_images_f32`. It is the first electrical-impedance-tomography family in the local or downstream corpus at any width (new modality).

The recipe emits complete reconstructed thoracic EIT image sequences from the Dräger PulmoVista 500 exports of PhysioNet's *Respiratory and heart rate monitoring dataset from aeration study* v1.0.0. There is one sample per continuous forced-expiratory-manoeuvre (FEM) recording, each shaped `frames × 32 × 32` in native little-endian float32.

## Source and rights

- Source: anonymous PhysioNet open-data bucket, `https://physionet-open.s3.amazonaws.com/respiratory-heartrate-dataset/1.0.0/`. This is the only published version (DOI 10.13026/e4dt-f689).
- Downloaded: all 20 `EIT_rawData/S01..S20_FEM.bin` files (332,079,600 B), plus `SHA256SUMS.txt`, `LICENSE.txt`, `README.txt` and `Code/read_binData.m` (53,591 B).
- Pinning: every file is pinned by SHA-256 and cross-checked against the pinned `SHA256SUMS.txt` (sha256 `e463d835…`).
- Licence: CC BY 4.0.
  - The physionet.org project page is "Open Access": "Anyone can access the files, as long as they conform to the terms of the specified license". It names the "Creative Commons Attribution 4.0 International Public License".
  - The release's `LICENSE.txt` (sha256 `9a78e7f2…`, listed in SHA256SUMS) is the CC BY 4.0 legal code.
- Safety: data from 20 consented healthy volunteers, named only S01-S20. `subject-info.csv` and the other physiological files are never downloaded. Only pixel values are emitted.

## Shape and conversion

- **Frame layout.** Each `.bin` is a headerless run of 4358-byte little-endian frames, per the authors' `read_binData.m`:
  - offset 0: a float64 time of day in days (MATLAB reads it as 2 float32)
  - offset 8: a dummy float32
  - offset 12: **1024 float32 pixels** (the primary)
  - after the pixels: 2 int32 (MinMax, event marker), 30 bytes of event text, an int32 timing error, and 52 float32 Medibus values (fill only)
- **Conversion.** The 4096 pixel bytes of each frame are copied bit-for-bit. Each recording becomes one sample, frames in stored order.
- **Orientation.** Read row-major, each block is the caudal-cranial display image: `reshape` + `rot90` + `flipud` amounts to a transpose of MATLAB's column-major fill.
- **Zeros.** The 29 out-of-mask corner pixels and the single all-zero reference frame per recording are native 0.0 and are kept.
- **Missing values.** There is no pixel sentinel. NaN or Inf, a size mismatch, a checksum mismatch, a timestamp outside [0,1) or a non-50 Hz median cadence is fatal.
- **Exclusion rule.** A recording is excluded if any frame step exceeds 30 ms (dropped frames). The rule is derived from content in both build and verify. It removes S02, S08 and S09 FEM (gaps of 91-120 ms). These three are also on a ~150× different scale (median per-frame max 7,329-8,690 AU against 23-67 AU retained), so keeping them would mix regimes.
- **Guards.** More than 5 exclusions, any derived set other than {S02, S08, S09}, or a retained median frame max above 1,000 AU is fatal.
- **Out of scope.** The PEEP and PEEP_BH trials: each set alone would be about 1.39 GB, over the 1 GB cap.

## Accepted output

| | value |
|---|---|
| Population validated | 20 FEM recordings (76,200 frames) |
| Excluded by rule | 3 (S02, S08, S09; 50,334,900 source bytes) |
| Primary samples | 17 |
| Frames | 64,650 |
| Primary values | 66,201,600 |
| Primary bytes | 264,806,400 |
| Smallest sample | 3,000 frames (3,072,000 values) |
| Median sample | 3,250 frames (3,328,000 values) |
| Largest sample | 8,400 frames (8,601,600 values) |
| Value range | -24.786 to 216.429 AU |
| Exact zeros | 2.858% |
| Non-finite values | 0 |
| Aggregate output SHA-256 | `a4429e0dd5d71ca467458d25b5d536176f9c0a8dae46201123fa7be6e35583a1` |

## Judge checks

- **Gate.** `python3 tools/autocollect/gate.py staging/physionet_eit_thorax_images_f32`: PASS, no warnings.
- **verify.sh.** I ran it myself twice; exit 0. The selftest passes, every frame is re-decoded and byte-compared, the exclusions are re-derived, and the aggregate SHA matches.
- **Network.** `build.sh`, `verify.sh` and `eit_bin.py` contain no network or credential references. `download.sh` is curl-only, anonymous, and pinned by SHA-256.
- **Frame layout** (independent struct decode of S01, S12, S16 and S02):
  - The timestamps are float64 day fractions (e.g. 11:29:31.173) stepping exactly 20 ms.
  - All 17 retained recordings have a median step of 20.0 ms, no gaps and no non-positive steps.
  - The Medibus floats are only -1000 / -3.4e38 fill.
- **Float bits** (S01, S12, S16, S18):
  - 94-96% of the 32-bit words are distinct.
  - Only ~0.013% of words have their low 13 mantissa bits all zero, so there is no float16 or integer lattice.
  - No quantization step; exponents spread from 2^-30 to 2^7.
- **Structure.**
  - Spatial neighbour correlation is 0.96-0.98, and the coarse frames show a two-lung pattern.
  - The global per-frame sum shows breathing and forced-expiration cycles.
  - Every recording has the same fixed 29-pixel corner mask and exactly one all-zero frame. 15 of the 17 carry MinMax = -1, matching the README.
- **Duplicates.** I hashed all 64,633 non-zero frames across the 17 samples: no duplicates, including among the six recordings that each have 3,050 frames.
- **Exclusion check.** In S02 and S09, subtracting the mean image still leaves deviations of hundreds to tens of thousands of AU (S09 frame 837: -21,579 to +62,083 AU). Retained recordings change by only ~0.1-0.5 AU per frame. The excluded recordings are a different regime, so the exclusion protects homogeneity rather than trimming inconvenient data.
- **Rights.** I fetched the physionet.org project page and confirmed Open Access, CC BY 4.0 and Version 1.0.0. I also confirmed that LICENSE.txt is the CC BY 4.0 legal code and is listed in SHA256SUMS.txt.
- **Novelty.**
  - `novelty.py` on the source URL and on terms (electrical impedance tomography, pulmovista, respiratory-heartrate, e4dt-f689, aeration, Draeger) matches only the candidate itself and the same-host `physionet_circor_pcg_i16` (phonocardiogram, a different project).
  - Broader terms (tomography, impedance, lung, thorax) hit only different modalities: neutron and TEM projections, battery EIS, PET volumes.
  - The four 32-bit families accepted in this effort are all neuro.
- **Volume.** 17 samples is the whole continuous FEM population. The other trial sets exceed the cap, and 265 MB is more than downstream's ~100 MB per-family selection.
