# WeatherBench2 ERA5 pressure-level fields float32 discovery

This candidate targets ERA5 reanalysis arrays distributed through the
WeatherBench2 public bucket and used as atmospheric inputs and reference data
for systems such as GraphCast and GenCast.

The natural sample is one physical variable at one analysis time, in the
source array's C-order dimension order:

```text
pressure_level x longitude x latitude = 13 x 240 x 121
```

Temperature, geopotential, specific humidity, U/V wind, and vertical velocity
remain six separate homogeneous streams. A pressure-level stack is retained
as one three-dimensional physical field because its levels form the vertical
atmospheric structure at the same time and location. Fields are never
interleaved.

This would add a genuinely new shape to the 32-bit corpus: global atmospheric
volumes with strong vertical correlation, latitude-dependent geometry,
longitude wraparound, and multiple physical regimes. Existing recipes contain
surface grids and unrelated 3D imaging volumes, but no global
pressure-by-latitude-by-longitude weather state.

Run the metadata-only preflight:

```sh
bash datasets/weatherbench2_era5_pressure_level_fields_f32/discover.sh
```

The script:

- reads the pinned WeatherBench2 data guide;
- enumerates only the official `datasets/era5/` directory boundary;
- selects a moderate-resolution consolidated Zarr store;
- downloads `.zmetadata`, `.zattrs`, and `.zgroup` only;
- inventories native float32 arrays, dimensions, chunks, and compression; and
- searches the ERA5 dataset prefix and selected store for explicit license or
  terms files.

No numerical Zarr chunk is requested. Do not proceed to payload acquisition
unless the exact hosted ERA5 material has explicit training-compatible reuse
terms and its pressure-level arrays are native little-endian float32.

## Discovery result

The exact `datasets/era5/` prefix publishes an 8,435-byte Copernicus license.
It grants a free, worldwide, non-exclusive, royalty-free, perpetual licence for
any lawful purpose, explicitly including reproduction, distribution,
adaptation, modification, and combination with other information. Public or
adapted outputs require Copernicus Climate Change Service attribution and the
specified European Commission/ECMWF disclaimer.

The initial automatic selection found six native little-endian float32
pressure-level arrays, but chose an older hourly 37-level store. The intended
recipe instead targets the current moderate-resolution six-hour store:

```text
datasets/era5/1959-2023_01_10-6h-240x121_equiangular_with_poles_conservative.zarr
```

Probe one `temperature` chunk and locally validate the Blosc/LZ4 plus byte
shuffle decoder:

```sh
bash datasets/weatherbench2_era5_pressure_level_fields_f32/probe_chunk.sh
```

This downloads one bounded numerical chunk only. It uses the system LZ4 shared
library through Python `ctypes`; no Python packages, xarray, or cloud SDK are
required.

The local decoder successfully expanded the probe chunk to eight complete
`13 × 240 × 121` temperature volumes with no non-finite values. Plan a bounded
six-variable corpus over eight seasonal/decadal windows:

```sh
bash datasets/weatherbench2_era5_pressure_level_fields_f32/plan.sh
```

This performs object-metadata requests only. The intended plan contains 48
generation-pinned compressed chunks and 384 output samples (eight timestamps
per chunk), totaling 579,870,720 native float32 bytes before compression.

## Recipe result

The deterministic plan selects eight six-hour Zarr chunks for each of the six
variables, centered on seasonal/decadal windows from 1960 through 2022. Each
chunk expands into eight individual analysis-time samples. The resulting
family contains:

- 64 samples per variable and 384 samples overall;
- 377,520 values and 1,510,080 bytes per sample;
- 24,161,280 values and 96,645,120 bytes per series; and
- 144,967,680 values and 579,870,720 bytes overall.

The download is 459,101,417 compressed bytes across 48 generation-pinned GCS
objects. The local decoder handles the precise Blosc/LZ4 plus byte-shuffle
layout used by this Zarr store through the system `liblz4.so.1`; it requires no
NumPy, xarray, Zarr, Blosc, or cloud SDK package.

Run acquisition, then build and verify locally:

```sh
bash datasets/weatherbench2_era5_pressure_level_fields_f32/download.sh
bash datasets/weatherbench2_era5_pressure_level_fields_f32/build.sh
bash datasets/weatherbench2_era5_pressure_level_fields_f32/verify.sh
```

The selected fields are native little-endian IEEE-754 float32. Building only
removes the Zarr compression and byte shuffle and splits chunks on the time
axis; it performs no numeric conversion, scaling, interpolation, regridding,
transposition, or field interleaving.

The hosted ERA5 material uses the ECMWF Copernicus Licence to Use Copernicus
Products v1.2. It permits reuse for any lawful purpose, including adaptation
and combination, subject to attribution. Required adapted-product notice:

> Contains modified Copernicus Climate Change Service information 2026.

Any publication or distribution must also state that neither the European
Commission nor ECMWF is responsible for any use that may be made of the
Copernicus information or data it contains.
