# worldclim_tavg_10m

- Date: 2026-06-01
- Status: needs_tooling
- Candidate dataset: WorldClim 10m average temperature
- Source: https://geodata.ucdavis.edu/climate/worldclim/2_1/base/wc2.1_10m_tavg.zip
- Why it looked promising: GeoTIFF climate rasters are on-scope numeric content.
- Failure class: missing_decoder_tooling
- What happened: The external import depends on GeoTIFF strip decoding. This repo currently lacks reviewed raster decode tooling.
- Evidence: External registry entry in ../training_data/numeric_datasets/public_datasets/repro/dataset_registry.csv and corresponding external manifest where present.
- Logs: No local download or build logs for this repo on this attempt; classification was done during registry-sync review before user-run acquisition.
- Decision: Record as tooling-limited rather than shipping a brittle raster parser.
- Retry conditions: Retry after adding approved GeoTIFF/raster decode support.
