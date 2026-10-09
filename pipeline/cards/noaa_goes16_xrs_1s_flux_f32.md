# GOES-16 EXIS X-Ray Sensor (XRS) Science-Quality 1-Second Solar Soft X-Ray Irradiance (XRS-A 0.05-0.4 nm, XRS-B 0.1-0.8 nm), Daily Files, Native Float32

- Candidate id: `noaa_goes16_xrs_1s_flux_f32`
- Width: float32
- Quantity: Whole-Sun soft X-ray irradiance at 1 AU (W/m^2) in the XRS-A and XRS-B channels at 1 s cadence
- Source: https://data.ngdc.noaa.gov/platforms/solar-space-observing-satellites/goes/goes16/l2/data/xrsf-l2-flx1s_science/
- Resources: https://data.ngdc.noaa.gov/platforms/solar-space-observing-satellites/goes/goes16/l2/data/xrsf-l2-flx1s_science/2022/06/sci_xrsf-l2-flx1s_g16_d20220601_v2-2-1.nc, https://data.ngdc.noaa.gov/platforms/solar-space-observing-satellites/goes/goes16/l2/docs/GOES-R_XRS_L2_Data_Users_Guide.pdf, https://www.ncei.noaa.gov/metadata/geoportal/rest/metadata/item/gov.noaa.ncei.swx:exis-l2-goesr/xml
- License: U.S. Government public domain (NOAA/NESDIS work, 17 U.S.C. 105); ISO record carries only citation request and liability disclaimer
- License evidence: https://www.ncei.noaa.gov/metadata/geoportal/rest/metadata/item/gov.noaa.ncei.swx:exis-l2-goesr/xml
- License quote: useConstraints: 'Cite this dataset when used as a source: Machol, Janet, Stefan Codrescu, and Rodney Viereck. GOES-R Series Extreme Ultraviolet and X-ray Irradiance Sensors (EXIS) Level 2 Products. NOAA National Centers for Environmental Information, 2018.' plus 'NCEI cannot assume liability for any damages...'; file attribute institution = 'DOC/NOAA/NESDIS'
- Natural record: One UTC-day science file per channel: xrsa_flux or xrsb_flux, 86,400 one-second values
- Estimated samples: 500
- Estimated primary values: 43,200,000
- Estimated download bytes: 800,000,000
- Estimated primary bytes: 172,800,000
- Decode path: NetCDF4/HDF5 (magic 89 48 44 46). Pure-stdlib HDF5 reader (superblock, object headers, chunked layout v1 B-tree, deflate via zlib, optional shuffle) as already done for ICON NetCDF4 recipes; read variables xrsa_flux and xrsb_flux (HDF5 float32 datatype messages observed in header), apply _FillValue/NaN policy, write little-endian float32.
- Novelty kind: new_quantity
- Measurement type: solar_xray_irradiance
- Instrument line: goes_r_exis_xrs
- Archive collection: data.ngdc.noaa.gov/goes16/l2/xrsf-l2-flx1s_science
- Novelty evidence: novelty.py --url xrsf-l2-flx1s_science and --terms xrs/x-ray irradiance/goes: no matches anywhere. --type solar_xray_irradiance: 0. Existing solar families are SILSO sunspot indices (monthly/daily index), DONKI flare catalog (event records), AIA EUV images; no high-cadence solar irradiance time series at any width. TSIS-1 SIM was screened out as thin, unrelated product.
- Homogeneity: Single satellite (GOES-16), single product (sci xrsf-l2-flx1s v2-2-1), one unit (W/m^2). XRS-A and XRS-B are separate series (different bands, ~10x scale difference). ~250 days spread 2017-2024 across solar minimum and maximum.
- Risks: Dtype of xrsa_flux inferred from 36 float32 HDF5 datatype messages in the first 64 KB (time is float64); builder must confirm. HDF5 decoding is nontrivial but has repo precedent. Extraction ratio ~22% (3.2 MB file -> ~0.7 MB kept). Quiet-Sun XRS-A sits near the noise floor with long flat stretches; eclipse-season gaps produce fills. NCEI rights rest on public-domain status rather than an explicit license string.
- Probe evidence: Directory listings 200 OK (years 2017-2025; daily files ~3.2 MB, e.g. sci_xrsf-l2-flx1s_g16_d20220601_v2-2-1.nc). 64 KB range GET: HDF5 superblock, variable names xrsa_flux, xrsb_flux, xrsa1/a2/b1/b2_flux, xrsb_flags, time; 36 float32 vs 2 float64 datatype messages. ISO record exis-l2-goesr fetched: constraints are citation + disclaimer only.

Proposed by the autocollect scout on 2026-10-08 (transcript `.data/pipeline/logs/scout_32bit/scout.20261008_164906.jsonl`).
