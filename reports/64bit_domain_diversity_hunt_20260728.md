# 64-bit Domain-Diversity Hunt — 2026-07-28

Goal: find native or operationally real 64-bit numeric material whose source
process and sample geometry differ from the accepted corpus. Width is fixed by
the collection goal; domain diversity is the ranking criterion.

No dataset payloads were downloaded during this hunt.

## Validation Result

The user ran the staged downloader on 2026-07-28. The exact DE440s kernel was
31.2 MiB (`32,726,016` bytes), downloaded in about three seconds, and had
SHA-256 `c1c7feeab882263fc493a9d5a5b2ddd71b54826cdf65d8d17a76126b260a49f2`.

After repairing the draft to report and exclude two special six-coefficient
segments, local build and independent verification passed:

- retained natural samples: `12`
- primary float64 values: `3,863,400`
- primary sample bytes: `30,907,200`
- median natural sample: `159,262.5` values
- retained sample range: `61,650` to `1,068,600` values
- excluded sub-floor segments: `2`, each with `6` values

The user reran the current downloader, which validated and reused the cached
kernel. The recipe was then promoted to `datasets/`.

## Grounding

The inventory started from committed `datasets/*/manifest.toml`,
`attempts/dataset_status.tsv`, and `reports/accepted_recipe_audit.tsv`. Scratch
content under `.data/` was not used as corpus evidence.

Accepted 64-bit coverage is already concentrated in:

- scalar weather, hydrology, atmospheric, energy, and finance time series
- API/catalog counters, identifiers, sizes, and timestamps
- geographic coordinates and tabular feature matrices
- population, public-health, and financial integer counts
- a smaller set of non-tabular material: sparse-matrix values, power-grid
  matrices, FITS image planes, and decoded vector geometry

The 2026-07-24 hunt already staged cybersecurity connection features, NOAA
flask CO2 observations, Global CMT moment tensors, and Bitcoin transaction
amounts. Those are not counted as new discoveries here.

## Ranked Candidates

| rank | candidate ID | material and natural sample | 64-bit source representation | diversity verdict | blocker / next action |
|---:|---|---|---|---|---|
| 1 | `nasa_naif_de440s_spk_coefficients_f64` | JPL DE440s planetary/lunar ephemeris; one DAF/SPK segment of Chebyshev coefficients per sample | SPK type-2/3 coefficient arrays are stored as IEEE-754 double words | **Very high.** Numerical ephemeris model coefficients differ from event tables, observed trajectories, rasters, and ordinary time series. | **Accepted:** 12 samples and 30,907,200 primary bytes. |
| 2 | `noaa_cors_rinex_observations_f64` | Raw GNSS receiver observations; one station-day-observable stream per sample (pseudorange, carrier phase, Doppler, signal strength) | RINEX observation fields are published decimal real values suitable for float64 preservation | **Very high.** Raw satellite-navigation signal observables add a measurement process not represented by processed coordinates or sensor tables. | Pin several exact NOAA CORS station/day `.o.gz` files and confirm each observable has median sample length >=1,000 before staging. Candidate root: `https://geodesy.noaa.gov/corsdata/rinex/`. |
| 3 | `proteomexchange_profile_mzml_f64` | Profile-mode mass spectra; one decoded spectrum m/z array per natural sample | mzML explicitly declares 64-bit float binary arrays (`MS:1000523`), commonly base64 plus zlib | **Very high.** Mass-spectrometer peak axes are a new irregular spectral-array geometry. | Select a permissively reusable ProteomeXchange project with exact `.mzML` URLs and enough profile spectra above 1,000 points; decode XML/base64/zlib rather than preserving mzML bytes. |
| 4 | `nasa_pds_gravity_harmonics_f64` | Planetary gravity spherical-harmonic model; coefficient triangles (Cnm/Snm and uncertainties) as model-field samples | PDS SHADR gravity products publish scientific-notation double coefficients | **High.** A global field expansion is structurally different from maps, point observations, and sparse matrices. | Pin one high-degree NASA PDS model with an exact label/data pair and verify that redistribution/attribution metadata are explicit. MRO SHADR format reference: `https://ode.rsl.wustl.edu/mars/pagehelp/Content/Missions_Instruments/Mars%20Reconnaissance%20Orbiter%20(MRO)/GRS/GRS%20SHADR.htm`. |
| 5 | `sourmash_genbank_minhash_u64` | Genomic MinHash sketches; one published genome signature per natural sample | sourmash signatures contain operational 64-bit hash minima | **High.** Machine-facing genomic sketches add unordered set-like integer samples, unlike base/token streams and biological tables. | Confirm the license and exact size of a bounded official precomputed signature collection. Do not generate arbitrary local hashes merely to obtain uint64 data. |
| 6 | `kepler_light_curve_flux_f64` | Stellar photometry; one target-quarter light curve per sample | Kepler FITS binary tables include double-precision time and may expose double flux columns | **Medium-high.** Time-domain stellar photometry is distinct, but still a scalar instrument time series. | Already identified on 2026-07-24. Requires a real FITS BINTABLE decoder and confirmation that the chosen flux field is actually 64-bit, not widened float32. |
| 7 | `cddis_vlbi_ngs_delays_f64` | Geodetic VLBI sessions; one session/baseline delay-observable stream per sample | NGS card-format observables are decimal double measurements | **High.** Intercontinental radio-interferometric delay measurements are a new instrument and geometry. | Confirm anonymous access (CDDIS may require Earthdata authentication), license terms, exact session files, and natural sample sizes. |
| 8 | `osm_history_way_references_i64` | Versioned map-edit topology; one history block or coherent regional history partition of way-node references | OSM PBF schema uses signed 64-bit IDs/references | **Medium.** Native topology is useful, but graph material already exists and unversioned Geofabrik `latest` extracts are not reproducibly pinned. | Use a versioned bounded history extract, decode protobuf fields, and emit actual IDs/references—not PBF container bytes. |

## Selection Notes

`nasa_naif_de440s_spk_coefficients_f64` wins because it satisfies all three
goals simultaneously:

1. the upstream field is genuinely stored as float64, so no gratuitous widening
2. an SPK segment is a documented, meaningful natural record
3. the material is a numerical celestial-mechanics model rather than another
   row-oriented measurement table

The staged decoder accepts DAF/SPK files, follows the summary-record chain,
decodes type-2 position Chebyshev records, removes only the per-record midpoint
and radius bookkeeping values, and emits the stored coefficient words in source
order. It rejects unsupported layouts, non-finite coefficients, malformed
record sizes, and output above the repository cap. Individually tiny SPK
segments are reported and excluded; aggregate and median floors are then
enforced over the retained natural samples.

## Deprioritized For This Round

- More UCI/CSV feature tables: useful, but insufficient shape diversity.
- Gaia astrometry as float64: `gaia_dr3_astrometry_f32` already covers the
  source, and widening its published decimal values would duplicate material.
- More catalog IDs, timestamps, and file sizes: 64-bit, but already abundant.
- Opaque HDF5/NetCDF/ROOT bytes: valid only after decoding documented typed
  variables with an approved local tool path.
- Radio/particle-event tables selected only because a parser emits Python
  doubles: storage width must be justified by the source schema.

## User Runbook For The Staged Candidate

```bash
bash datasets/nasa_naif_de440s_spk_coefficients_f64/download.sh
bash datasets/nasa_naif_de440s_spk_coefficients_f64/build.sh
bash datasets/nasa_naif_de440s_spk_coefficients_f64/verify.sh
```

The user ran the current downloader and local build/verification succeeded
before promotion.
