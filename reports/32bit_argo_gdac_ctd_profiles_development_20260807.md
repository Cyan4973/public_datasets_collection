# Argo GDAC CTD profile-history float32 development — 2026-08-07

## Outcome

Accepted `argo_gdac_ctd_profiles_f32`: complete raw pressure, temperature, and
practical-salinity profile-history matrices from 46 autonomous ocean floats in
the official Argo GDAC.

## Domain and shape value

This family adds vertical subsurface ocean structure measured repeatedly by
autonomous profiling instruments. It differs from surface weather and water
stations, coastal ADCP velocity words, vessel AIS reports, and two-dimensional
remote-sensing rasters.

Each natural sample is one complete physical-variable matrix for one float,
with axes `profile cycle x depth-level slot`. The 46 distinct shapes range from
`23–522` profiles by `54–2084` levels. This produces 138 variable-sized 2D
samples rather than artificially cutting a shared table or concatenating
independent floats.

## License and source selection

Argo's official acknowledgement page states: “Argo data are freely available
without restriction.” It asks users to acknowledge Argo and provides the GDAC
DOI `10.17882/42182` and recommended citations.

The official global metadata index contained 20,854 floats. A stable hash-based
probe inspected 80 floats across DACs using only remote sizes and bounded
classic-NetCDF headers. Forty-seven files declared `PRES`, `TEMP`, and `PSAL`
as `NC_FLOAT(N_PROF,N_LEVELS)`. One of those, WMO `3902123`, was excluded after
complete inspection because all three `554 x 2420` matrices contained only
59,074 measurements (4.41% coverage); a few high-resolution profiles forced
extensive padding across many shorter profiles.

The retained 46 files span ten DACs and total 239,866,364 source bytes. Every
URL, exact size, and complete SHA-256 is pinned in `download_plan.tsv`.

## Accepted material

- 46 floats and 138 matrices: 46 each for `PRES`, `TEMP`, and `PSAL`
- 4,703,029 float32 cells and 18,812,116 bytes per variable family
- 14,109,087 cells and 56,436,348 primary bytes total
- 11,047,396 non-fill cells and 3,061,691 native fill cells
- median non-fill coverage 97.53%; minimum retained coverage 19.43%
- 46 unique natural matrix shapes
- 8,607–536,616 cells per sample; median 27,891

Observed non-fill stored ranges are:

- pressure: `-4.0` through `6553.5`
- temperature: `-5.0` through approximately `58.628`
- practical salinity: approximately `-249.898` through `175.11`

These are raw Argo variables. Source QC flags are deliberately not applied, so
physically implausible QC-invalid sensor values remain part of the native
numeric streams. “Non-fill” therefore means stored data rather than a claim of
scientific validity.

## Representation and verification

All retained files are classic NetCDF CDF1. Their profile variables are
interleaved record variables, not contiguous slabs. The dependency-free parser
validates dimensions, attributes, record sizes and offsets, then reads every
record chunk. Source NC_FLOAT words are big-endian; outputs preserve the exact
float32 words and matrix order while converting to canonical little-endian.

The native `_FillValue=99999.0` cells are retained to preserve each natural
rectangular matrix. Build and independent verification enforce source hashes,
source-to-output conversion, output hashes, finite non-fill values, coverage
floors, non-degeneracy, sample inventories, shapes, and aggregate totals.
