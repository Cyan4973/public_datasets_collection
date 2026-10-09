# TERN OzFlux L3 eddy-covariance flux float64 development

## Outcome

Accepted `tern_ozflux_l3_eddy_covariance_fluxes_f64`. The family covers quality-controlled half-hourly turbulent surface fluxes from the TERN Ecosystem Processes / OzFlux tower network, at Level 3 of the PyFluxPro chain ("default" folder; QA/QC applied, not gap-filled). There are three primary series, one per flux variable:

- CO2 flux `Fco2` (umol m-2 s-1)
- latent heat flux `Fe` (W m-2)
- sensible heat flux `Fh` (W m-2)

This is the first eddy-covariance / flux-tower family in the corpus, at any width and in the downstream mirror. The nearest existing material is in-situ meteorological station series and NASA POWER reanalysis radiative fluxes, which are smooth state variables or modelled daily values rather than 30-minute covariance-derived fluxes. The novelty is therefore recorded as a new source (and a new quantity), not a new modality.

## Source and rights

- Source: TERN THREDDS/OPeNDAP, `https://dap.tern.org.au/thredds/catalog/ecosystem_process/ozflux/`
- Objects: 51 L3/default NetCDF files, pinned in `files.tsv` at each site's newest release folder (2024_v2 to 2026_v3, crawled 2026-10-09)
- Excluded: two 60-minute files, `Otway_L3.nc` and `Tumbarumba1_..._L3.nc`
- Retrieval: server-side projections `<file>.nc.dods?V.V` for V in Fco2, Fe, Fh, plus `.dds` and `.das` per file
- Download: 156,221,041 bytes
- License: CC BY 4.0, declared in every file's global attributes (`license "https://creativecommons.org/licenses/by/4.0/"`, `license_name "CC BY 4.0"`). `download.sh` re-checks both for each file.
- Attribution: the TERN acknowledgement string and Isaac et al. (2017), Biogeosciences 14, 2903-2928, are recorded in the manifest.
- No upstream checksums: OPeNDAP responses carry no ETag. Integrity rests on the structural checks plus per-sample SHA-256 values in the index.

## Shape and conversion

Each natural record is one tower file. Five sites have two files, covering separate towers or periods. Each file gives one sample per flux variable: every valid half-hour value, in time order.

The `.dods` payload consists of:

- a DDS header declaring `Float64 V[time = N][latitude = 1][longitude = 1]` and the dataset path
- the separator `\nData:\n`
- two equal big-endian uint32 XDR length words, both equal to the pinned N
- exactly N big-endian doubles

These are decoded and written as little-endian `<d`. Values equal to -9999.0, NaN/Inf, or the NetCDF default fill are dropped. Fill-run positions are written to `filtered/.../gaps/<series>/<stem>.json`, so the half-hour axis can be rebuilt. The declared `valid_range` is not applied, because L3 does not enforce it; finite values with |x| > 1e5 are fatal.

The processing level and missing-value policy apply to all 51 files:

- Fill share is 29.9% for Fco2, 26.6% for Fe and 25.1% for Fh.
- No (file, variable) pair fell below the 1,000-valid skip threshold.

## Accepted output

| series | samples | values | bytes | min / median / max sample (values) | aggregate SHA-256 |
|---|---|---|---|---|---|
| `ozflux_l3_fco2_f64` | 51 | 4,506,743 | 36,053,944 | 5,868 / 62,630 / 320,061 | `354114076c178df60e08915676858ae9e81e09bb73c50c1cca4f1cfa8aa73325` |
| `ozflux_l3_fe_f64` | 51 | 4,718,845 | 37,750,760 | 5,875 / 64,998 / 328,627 | `659891ed88f859fe3d6f34579771c3319c489b54cb7b0d4aec85a9c59d0ad1cc` |
| `ozflux_l3_fh_f64` | 51 | 4,816,998 | 38,535,984 | 5,873 / 71,885 / 328,525 | `451a2b10f873045697bb1a52b1bbf993a59f919a286d7f4c95d9295344dc3a47` |

- Totals: 153 samples, 14,042,586 values, 112,340,688 bytes, from 46 sites and 6,432,235 half-hour steps per variable.
- Breadth (zlsim): verdict OK. The nearest families are:
  - Fco2: NAIF DE440s SPK coefficients, distance 0.052 / loss 0.023
  - Fe: GRAIL KBR1C range acceleration, distance 0.046 / loss 0.031
  - Fh: GRAIL KBR1C range acceleration, distance 0.039 / loss 0.031
- Each series clears only one of the two similarity criteria, so none is redundant, but all sit near the thresholds.

## Judge checks

- **Gate:** `gate.py` passes with no warnings.
- **Verify:** I re-ran `verify.sh`. It passed, including the byte-for-byte re-decode of all 153 samples with the independent array/byteswap decoder.
- **Build is local-only:** `build.sh` only reads `.data/downloads`.
- **Bytes:** I decoded all 153 samples with `struct` (scratch under `/tmp/autocollect/`).
  - Ranges are physical, and site-specific L3 range limits are visible as clipping (Fco2 within ±25 at DryRiver, ±10 at GreatWesternWoodlands).
  - Distinct-value share is 98-100% per sample; the longest repeated run is 8; integer share is at most 0.36%; the top mode is 0.0 at 0.005-0.012%.
  - The float32 round-trip share is about 0, so these are genuine doubles.
  - HowardSprings Fh autocorrelation is 0.84 at lag 1 and 0.53 at lag 48: a diurnal turbulent-flux series, not noise or concatenation.
- **Duplicates:** exact-value overlap between samples is at most 2.4% and occurs only among sites with decimal-rounded values. These are chance collisions, not copies.
- **Precision subset:** about 8% of Fe/Fh values carry 6-7-significant-digit decimals stored as double.
  - Wholly decimal: AlpinePeatland, Boolcoomatta, Dookie1, MyallValeA/B, Wedgetail, SilverPlains, SnowGum, DigbyPlantation.
  - Partly decimal: CumberlandPlain, GatumPasture, Collie; for Fco2 mainly GatumPasture (40%).
  - These are native values of the same L3 product with the same unit, standard_name and lattice, so I judged them natural variation rather than a mix of regimes.
- **Extremes:** these are source values passed by site L3 limits: Tumbarumba2 Fe reaches 1757 and -568, and Whroo2 Fh reaches -612.
- **Homogeneity:** I parsed all 51 DAS files. Each variable has the same long_name, units and CF standard_name everywhere; `time_step` 30 and `processing_level` L3 are checked per file. Sonic models vary (CSAT3/3A/3B, IRGASON, one WindMaster Pro), but the method is the same.
- **Rights:** `license_name "CC BY 4.0"` is present in 51 of 51 DAS files. The scripts contain no credentials. PI contact attributes are not emitted.
- **Novelty:** `novelty.py --url` (OzFlux catalog) matches only this staging recipe. The terms ozflux, eddy covariance, fluxnet, ameriflux, PyFluxPro, latent heat, sensible heat and flux tower find nothing in datasets, the registry or downstream; the `icos` hit is a substring false positive. `--type/--instrument/--archive` gives 0/0/0.
- **Residual risks:** some pinned release folders may be withdrawn upstream (download would fail loudly); there are no upstream checksums.
