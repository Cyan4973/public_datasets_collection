# TSIS-1 SIM Level-3 12-Hour Solar Spectral Irradiance Spectra at 1 AU, 200-2400 nm (V14) Float64

- Candidate id: `tsis1_sim_l3_solar_spectral_irradiance_f64`
- Width: float64
- Quantity: Solar spectral irradiance at 1 AU in W m^-2 nm^-1 on a fixed 2,104-point wavelength grid (200-2400 nm), measured by the Spectral Irradiance Monitor on NASA's TSIS-1 (ISS), 12-hour cadence, 2018-03 to 2026 (V14 release). Variable irradiance_1au.
- Source: https://lasp.colorado.edu/data/tsis/ssi_data/V14/
- Resources: https://lasp.colorado.edu/data/tsis/ssi_data/V14/tsis_ssi_L3_c12h_latest.nc, https://lasp.colorado.edu/data/tsis/ssi_data/release_notes/TSIS_SIM_V14.0_Release_Notes.pdf, https://www.earthdata.nasa.gov/engage/open-data-services-software-policies/data-use-guidance, https://doi.org/10.5067/TSIS/SIM/DATA327
- License: CC0-1.0 (NASA-led mission data per NASA Earthdata data-use guidance; product DOI 10.5067/TSIS/SIM/DATA327)
- License evidence: https://www.earthdata.nasa.gov/engage/open-data-services-software-policies/data-use-guidance
- License quote: "Unless the content is marked with a use restriction or license, data provided from a NASA-led mission are licensed as Creative Commons Zero (CC0). While there are no restrictions on the use of these data, data users are very strongly urged to cite the data used in their work products."
- Natural record: One 12-hour SIM L3 spectrum (one row of irradiance_1au, 2,104 wavelengths), stored in the file as one HDF5 chunk per spectrum. The V14 file holds 5,025 spectra.
- Estimated samples: 5,025
- Estimated primary values: 10,572,600
- Estimated download bytes: 226,689,168
- Estimated primary bytes: 84,580,800
- Decode path: NetCDF4/HDF5 (h5lite-compatible: links and the v1 B-tree chunk index parsed in the probe). irradiance_1au is float64 (5025, 2104), chunk (1, 2104), deflate only, so each chunk inflates directly to 2,104 little-endian doubles. Root attributes sit in a fractal heap with 'huge objects', which h5lite rejects; the builder should skip root attributes or extend the reader. One file, one curl download with -C - resume, pinned by size 226,689,168 and ETag 6a398c0f-d830090 plus a SHA-256.
- Novelty kind: new_modality
- Novelty evidence: novelty.py --url .../tsis/ssi_data/V14/tsis_ssi_L3_c12h_latest.nc --terms TSIS 'spectral irradiance' LASP: no matches in URLs, recipes, registry, ledger or downstream. No solar irradiance spectra exist in the corpus at any width; NASA POWER solar-flux families are modeled surface broadband fluxes, not measured top-of-atmosphere spectra.
- Homogeneity: One instrument (SIM), one release (V14), one product (12-hour L3), one quantity and unit (irradiance_1au), one fixed wavelength grid. irradiance_true_earth (the same measurement rescaled by distance) and the f32 uncertainty arrays are excluded, so there are no duplicate views. quality (int64) is an auxiliary mask at most.
- Risks: (1) Near-duplicate series: consecutive spectra differ by a median relative 1.9e-4 (p90 9e-4), so the family is 5,025 highly similar fixed-length spectra, which the criteria list as weak material. Within-sample structure is rich (0.007-2.1 W/m^2/nm with Fraunhofer lines). (2) Values are decimal-rounded to ~9 significant digits (e.g. 0.0407362066). f64 is still required for exact representation, but entropy is lower than raw doubles. (3) The access copy is LASP's (the NASA GES DISC copy needs Earthdata login), and the LASP page carries no license text of its own; rights rest on the NASA CC0 statement for NASA-led missions. (4) The top-level 'latest' file is newer (5,290 spectra); pin the V14/ directory copy.
- Probe evidence: One-byte range GET with -L on V14/tsis_ssi_L3_c12h_latest.nc returned 206. HEAD gave Content-Length 226,689,168, Last-Modified 22 Jun 2026, ETag "6a398c0f-d830090". A lazy HDF5 range walk listed irradiance_1au float64 (5025, 2104), irradiance_true_earth float64, quality int64, wavelength float32 (2104), uncertainties float32. Decoded chunks 100, 2000 and 4000 gave 2,104/2,104 finite values each, range 0.0069-2.106, stored ~15.9 KB per 16.8 KB raw chunk. The text-format header (V14) declares irradiance_1AU as R8, e15.8, W/m^2/nm, DOI 10.5067/TSIS/SIM/DATA327.

Proposed by the autocollect scout on 2026-10-06 (transcript `.data/pipeline/logs/scout_64bit/scout.20261006_034331.jsonl`).
