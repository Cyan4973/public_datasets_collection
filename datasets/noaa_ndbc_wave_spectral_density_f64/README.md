# NOAA NDBC Wave Spectral Density

Bounded NOAA NDBC historical spectral wave density recipe. This is intentionally
not another scalar station weather series: each primary sample is a native
time-by-frequency wave-energy grid for one station-year file.

Scope:

- product: NDBC historical `swden` spectral wave density
- stations: `41002`, `41004`, `42001`, `42002`, `46002`, `46042`, `46047`, `51001`
- years: `2021` through `2023`
- resources: `24` gzip-compressed text files
- natural sample boundary: one station-year spectral-density grid

Run:

```bash
bash datasets/noaa_ndbc_wave_spectral_density_f64/download.sh
bash datasets/noaa_ndbc_wave_spectral_density_f64/build.sh
bash datasets/noaa_ndbc_wave_spectral_density_f64/verify.sh
```

Rows with NDBC missing sentinels in any frequency bin are skipped so the emitted
sample remains a dense rectangular grid over retained timestamps and native
frequency bins.

Validated local output:

- source resources: 24
- source bytes: 13,558,316
- primary samples: 24
- primary values: 11,719,309
- primary bytes: 93,754,472
- primary value count range: 106,690 / 427,159.5 / 819,586 min/median/max
- primary size range: 853,520 / 3,417,276 / 6,556,688 bytes min/median/max
- source data rows retained: 249,347 / 249,347
