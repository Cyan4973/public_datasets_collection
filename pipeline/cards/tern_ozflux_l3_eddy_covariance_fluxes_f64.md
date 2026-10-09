# TERN OzFlux Level-3 Eddy-Covariance Half-Hourly Turbulent Fluxes (CO2 Flux Fco2, Latent Heat Fe, Sensible Heat Fh), 51 Australian Flux Towers, Float64

- Candidate id: `tern_ozflux_l3_eddy_covariance_fluxes_f64`
- Width: float64
- Quantity: Quality-controlled 30-minute eddy-covariance surface fluxes from the CSAT3 sonic anemometer and LI-7500 open-path IRGA at each tower: Fco2 (umol m-2 s-1), Fe (W m-2) and Fh (W m-2). These are native NetCDF Float64 variables with full double precision (e.g. 0.478940778000329, -2.471715714560184), and they are noisy turbulent fluxes with diurnal structure.
- Source: https://dap.tern.org.au/thredds/catalog/ecosystem_process/ozflux/catalog.html
- Resources: https://dap.tern.org.au/thredds/catalog/ecosystem_process/ozflux/catalog.xml, https://dap.tern.org.au/thredds/fileServer/ecosystem_process/ozflux/Readme.txt, https://dap.tern.org.au/thredds/dodsC/ecosystem_process/ozflux/AliceSpringsMulga/2026_v2/L3/default/AliceSpringsMulga1_20100903T0000_to_20230308T0900_L3.nc.dds, https://dap.tern.org.au/thredds/dodsC/ecosystem_process/ozflux/AdelaideRiver/2026_v2/L3/default/AdelaideRiver_20071017T1130_to_20090524T0600_L3.nc.dods?Fco2.Fco2
- License: CC-BY-4.0
- License evidence: https://dap.tern.org.au/thredds/dodsC/ecosystem_process/ozflux/AliceSpringsMulga/2026_v1/L3/default/AliceSpringsMulga1_L3.nc.das
- License quote: String license "https://creativecommons.org/licenses/by/4.0/"; String license_name "CC BY 4.0"; (global attributes embedded in every L3 file; all 53 probed L3 files report license_name "CC BY 4.0")
- Natural record: One tower record: the complete L3 'default' (PyFluxPro) file for one site from that site's latest release folder, one sample per flux variable per site file. Three primary series (fco2, fe, fh), each with about 51 samples.
- Estimated samples: 51
- Estimated primary values: 16,000,000
- Estimated download bytes: 155,000,000
- Estimated primary bytes: 125,000,000
- Decode path: Pin the per-site release and file list (crawled: 53 L3 files, 2024_v2..2026_v3). For each file, curl the OPeNDAP binary subset '<file>.nc.dods?Fco2.Fco2' (and the same for Fe and Fh). The response is a DDS text header, then '\nData:\n', then two big-endian uint32 length words, then n big-endian XDR float64. Decode with struct '>II' + '>%dd' and repack little-endian. The fileServer full .nc (5-150 MB, many variables) is the fallback. Missing values are -9999.0 (about 18% in one probed file); drop them or emit them with a declared policy and an optional auxiliary time index. Stdlib only, already verified on one file.
- Novelty kind: new_modality
- Measurement type: eddy_covariance_flux
- Instrument line: CSAT3 sonic anemometer + LI-COR LI-7500 open-path IRGA flux towers (PyFluxPro L3)
- Archive collection: tern_ozflux_thredds
- Novelty evidence: novelty.py --url on the OzFlux THREDDS catalog: no URL matches. The terms ozflux / 'eddy covariance' match nothing (the 'tern' hits are only substring matches inside 'pattern'). --type eddy_covariance_flux --archive tern_ozflux: 0 same type, 0 same archive. No turbulent surface-flux family exists at any width. Existing 64-bit met families (NASA POWER, CO-OPS, NDBC) are smooth, low-precision state variables, not covariance-derived fluxes.
- Homogeneity: One network, one processing chain (PyFluxPro L3 default), and the same sensors (CSAT3 sonic + LI-7500-family IRGA), half-hourly cadence and unit per series. Each variable is its own series (Fco2 in umol/m2/s, Fe and Fh in W/m2), so units never mix within a series. Exclude the two 60-minute files (Otway_L3.nc, Tumbarumba1) to keep one tick regime: 51 of 53 files have time_step 30. Do not use L4-L6 gap-filled or model-partitioned products.
- Risks: (1) Fe and Fh have strong diurnal cycles that could resemble existing station-series families on bytes; Fco2 is the most distinct. If the gate is a concern, Fco2 alone gives about 51 MB. (2) The fill fraction (-9999) varies by site, so dropping fill changes per-sample lengths; declare the policy. (3) OPeNDAP subsetting is server-side but returns the identical native Float64 values; the fileServer fallback costs about 3 GB for all files. (4) Releases are versioned (e.g. 2026_v2), so pin exact paths, and validate the length words and the -50..50 / -100..600 valid ranges.
- Probe evidence: The THREDDS catalog is live: 94 catalogRefs, and a crawl found 53 L3/default files across 47 sites. DDS and DAS calls for all 53 returned Float64 Fco2/Fe/Fh with time lengths of 6,171-431,678 (total 6,645,215 per variable), time_step 30 for 51 files and 60 for 2, and license_name 'CC BY 4.0' in every file. A full .dods?Fco2.Fco2 subset for AdelaideRiver (224,790 bytes) decoded to 28,070 values: 23,038 distinct, 5,033 equal to -9999. An ASCII slice shows 15-17 significant-digit values. A 1-byte range GET with -L on the fileServer URL returned 206. Global attributes give instrument 'CSAT3,Li-7500RS' and PyFluxPro V3.4.23.

Proposed by the autocollect scout on 2026-10-09 (transcript `.data/pipeline/logs/scout_64bit/scout.20261009_085026.jsonl`).
