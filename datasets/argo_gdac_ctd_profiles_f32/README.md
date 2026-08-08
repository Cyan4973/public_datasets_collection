# Argo GDAC CTD Profiles Float32 — Preflight

This candidate targets complete multi-profile NetCDF files from autonomous
Argo ocean floats. The primary variables are pressure (`PRES`), temperature
(`TEMP`), and practical salinity (`PSAL`).

Run:

```bash
bash datasets/argo_gdac_ctd_profiles_f32/discover.sh
bash datasets/argo_gdac_ctd_profiles_f32/download.sh
bash datasets/argo_gdac_ctd_profiles_f32/build.sh
bash datasets/argo_gdac_ctd_profiles_f32/verify.sh
```

The license-first preflight reads the official Argo data-policy page and the
small global metadata index. It deterministically probes at most 80 official
multi-profile files across data assembly centres using `HEAD` and a bounded
1 MiB range. It accepts only classic NetCDF files whose headers declare all
three CTD variables as two-dimensional `NC_FLOAT` (`float32`) arrays over
`N_PROF x N_LEVELS`.

Discovery downloads no complete profile file. Results are written under
`.data/discovery/argo_gdac_ctd_profiles_f32/`.

The pinned acquisition contains 46 multi-profile files from ten Argo data
assembly centres: 239,866,364 source bytes. The build extracts each complete
`PRES`, `TEMP`, and `PSAL` matrix as a separate little-endian float32 sample,
preserving its natural `N_PROF x N_LEVELS` shape and native fill values. The
expected primary output is 138 samples and 56,436,348 bytes. Build and verify
reject matrices with fewer than 1,000 valid measurements, less than 5% valid
coverage, non-finite stored measurements, or degenerate valid values.

WMO `3902123` is deliberately excluded after complete-payload inspection: all
three of its `554 x 2420` matrices contain only 4.41% measurements because a
few very high-resolution profiles force extensive fill padding. Every retained
matrix has at least 19.4% valid coverage.

Argo states that its data are freely available without restriction and asks
users to acknowledge Argo and cite the recommended data paper.
