# NOAA STOFS-2D-Global ADCIRC station water-level float64 development

## Outcome

Accepted `noaa_stofs2d_glo_adcirc_station_water_level_f64` from the NOAA Open Data Dissemination (NODD) bucket `noaa-gestofs-pds`.

The primary series is the native `zeta` variable of STOFS-2D-Global v2.1's ADCIRC station output file `stofs_2d_glo_fcst.61.nc` ("fort.61"). It is simulated water-surface elevation above the geoid, combining tide, GFS-forced surge and sea-ice effects, at 1,688 fixed output stations, every 6 minutes from cycle −5.9 h to cycle +120 h.

The family differs from the accepted `noaa_coops_water_level` and `noaa_tides_water_level` recipes:
- **Those recipes:** observed CO-OPS gauge levels at a handful of stations, decimal-quantized.
- **This recipe:** the same physical quantity from a global unstructured-mesh hydrodynamic simulation, written as full-mantissa doubles.

## Source and rights

- **Source:** `https://noaa-gestofs-pds.s3.amazonaws.com/stofs_2d_glo.YYYYMMDD/00/rerun/stofs_2d_glo_fcst.61.nc`, 00z cycles, 2024-06-01 + 20k days for k = 0..39 (last cycle 2026-07-21).
- **Downloaded bytes:** 632,438,615 in 40 objects.
- **Pins:** per-object key, size and S3 multipart ETag (8 MiB parts, recomputed locally) are in `sources.tsv`. That file is itself pinned by SHA-256 `26338f9530df0c1d6bec2df2a6d2e53df69fdc91c46ed20972aa1e23c7a89d6d` and must follow the 00z/20-day lattice.
- **Model version:** global attribute `version = noaa.stofs.2d.glo.v2.1.0r1.v55.12`, ADCIRC on an OceanMesh2D grid.
- **License:** NOAA NODD open data. The AWS Registry entry `noaa-gestofs.yaml` (resource `arn:aws:s3:::noaa-gestofs-pds`) states: "NOAA data disseminated through NODD are open to the public and can be used as desired ... NOAA requests attribution for the use or dissemination of unaltered NOAA data."
- **Citation:** DOI 10.25923/ng4h-4b85.
- **`rerun/` folder:** the bucket README describes it as "stored for NOAA internal reference". The objects are public in the same anonymous, non-requester-pays NODD bucket under the same terms.

## Shape and conversion

Each natural record is one 00z cycle's fort.61 file. The sample is that file's complete `zeta` matrix:
- 1260 time steps × 1688 stations
- float64 little-endian
- native time-major order

The file is NetCDF4/HDF5 with chunks (1, 1688), filter pipeline exactly `[shuffle(8), deflate(2)]`, and a version-1 chunk B-tree. It is decoded with the pure-stdlib `scripts/h5lite.py`, an exact copy of the reader in the accepted `noaa_cdr_seaice_conc_nh_daily_u8` recipe.

Each chunk is inflated to exactly 13,504 bytes and byte-unshuffled. The rows are concatenated in time order and no value is changed.

Every file is checked against the same pinned values:
- version, model, grid, title, runid, `_NCProperties`, `dt`, `ihot`
- `rundes` and `rnday` matching the cycle
- time axis equal to cycle − 21600 s + 360 s·(i+1)
- station coordinates and names (SHA-pinned, with one cosmetic rename of index 68 from 2025-03-08)

Excluded:
- older V1.1.0 files (1687 stations, 960 steps)
- STOFS v3.1 cycles (from 2026-08-17 12z)
- 06/12/18z cycles, whose windows would overlap the 00z ones
- the post-processed `points.cwl.nc` product, which is datum-adjusted and decimal-rounded

Missing values:
- **Fill kept:** the native −99999.0 dry-node `_FillValue`/`dry_Value` stays in place and is counted per sample.
- **Fatal values:** any NaN, Inf or non-fill value outside (−100, 500) m is fatal; nothing is clipped.
- **Station 119** (Fajardo PR) is fill at every step and stays as an all-fill column.
- **Station 1649** (`UJ816 SOUS00 SA816`, Sea of Azov coast) carries an unphysical 45.9–219.8 m native model level in every cycle. It is kept as published and documented in the manifest and README.

## Accepted output

| | |
|---|---|
| Source files validated | 40 (632,438,615 bytes) |
| Primary samples | 40 |
| Primary values | 85,075,200 |
| Primary bytes | 680,601,600 |
| Values per sample (min = median = max) | 2,126,880 (17,015,040 bytes) |
| Fill values | 132,410 (0.156%) |
| Stations with any fill per cycle | 6–33 |
| Non-fill range, excluding station 1649 | −10.7259 to +8.2283 m |
| Per-cycle maximum, excluding station 1649 | 4.20–8.23 m |
| Station 1649 range | 45.91–219.80 m |
| Distinct values per sample | about 2.12 M |
| Aggregate decoded SHA-256 | `4be5fd63a03f64774bea9dac45492458916a90eb4b17b5d982568756fb186d7c` |

The local build and the independent verification both completed successfully against the pinned objects. Verification takes a different route from build: it walks the B-tree leaf sibling chain and re-shuffles each stored step for a byte comparison.

## Judge checks

- **Gate:** `tools/autocollect/gate.py` passed with no warnings (values=85075200, bytes=680601600, samples=40, median=2126880, widths=[64]).
- **verify.sh:** my own run succeeded, including the synthetic HDF5 self-test with 20+ rejection cases, and reproduced the aggregate SHA-256 above. build.sh reads only local files; the Python scripts contain no network code; no credentials appear anywhere.
- **Independent decode:** in three raw files (20240601, 20250308, 20260721) I brute-force scanned for zlib streams without using any HDF5 index. Each file has exactly 1260 streams inflating to 13,504 bytes. After unshuffling, all 1260 equal distinct sample rows, and file order equals time order.
- **Precision:** in 4 samples, 0 of about 42.5k subsampled non-fill values are float32-exact and 0 are 6-decimal-exact. The mantissa trailing-zero histogram halves per bit, consistent with genuine full-precision float64 model output, not widened or rounded data.
- **Realized ranges:** recomputed over all 40 samples, they match the manifest and README claims (see the table). Station 1649 and the all-fill station 119 behave as documented. No value repeats at the same position between consecutive cycles.
- **h5lite provenance:** `scripts/h5lite.py` is byte-identical to the accepted noaa_cdr_seaice copy.
- **License:** I fetched `awslabs/open-data-registry/datasets/noaa-gestofs.yaml` myself and confirmed the NODD license text and that it covers the whole bucket. The bucket README confirms the v2.1/v3.1 version windows and the `rerun/` description.
- **Novelty:** `tools/autocollect/novelty.py` with the bucket URL and the terms stofs, adcirc, gestofs, storm surge, fort.61, sea_surface_height and geoid found only this candidate; registry and downstream returned none. No ocean or hydrodynamic-model family is accepted at 64-bit in the ledger.
