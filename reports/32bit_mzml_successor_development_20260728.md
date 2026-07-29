# 32-bit mzML Successor Development — 2026-07-28

The rejected float64 attempt against Zenodo record `10054333` established that
the study's mzML arrays are native float32 centroid data. A semantically coherent
32-bit successor is nevertheless viable.

Local inspection of `2D_Frac_10-12a.mzML` found 706 positive-ion MS1 survey
spectra with 1,563,833 points per array family and median natural length 2,360.
MS2 spectra were excluded by acquisition level, not by size. The negative run
was excluded because its MS1 median was only 827.

The staged successor pins two related positive pooled late-fraction runs,
`2D_Frac_10-12a.mzML` and `2D_Frac_10-12b.mzML`. It emits every positive
centroid MS1 m/z and intensity array as its own float32 sample, without widening,
length filtering, or concatenation.

## Realized result

The user ran the current downloader and both source files passed Zenodo MD5 and
local XML validation. Local build and independent verification accepted:

- source files / bytes: `2` / `76,710,628`
- positive-ion MS1 spectra: `1,401`
- primary samples / values / bytes: `2,802` / `6,232,014` / `24,928,056`
- median natural sample: `2,368` values
- natural sample range: `133` to `4,250` values

The recipe was promoted to `datasets/zenodo_marine_dom_positive_ms1_f32/`.

```bash
bash datasets/zenodo_marine_dom_positive_ms1_f32/download.sh
bash datasets/zenodo_marine_dom_positive_ms1_f32/build.sh
bash datasets/zenodo_marine_dom_positive_ms1_f32/verify.sh
```
