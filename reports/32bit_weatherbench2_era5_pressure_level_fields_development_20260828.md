# WeatherBench2 ERA5 Pressure-Level Fields Float32 — 2026-08-28

## Outcome

`weatherbench2_era5_pressure_level_fields_f32` adds 384 native float32 global
atmospheric volumes containing 144,967,680 values and 579,870,720 bytes. Six
physical variables each contribute 64 analysis-time samples. Every sample has
shape `13 x 240 x 121` in source C-order
`pressure_level x longitude x latitude`, with 377,520 values and 1,510,080
bytes.

## Why this is new

The accepted 32-bit corpus contains surface rasters, astronomical maps,
medical and radar volumes, physical time series, geometric coordinates, and
neural-network tensors. It did not contain vertically stacked global weather
states over pressure levels. These samples add strong vertical correlations,
latitude-dependent spatial structure, longitude wraparound, and distinct
meteorological regimes within fixed three-dimensional records.

The six physical variables remain separate homogeneous series. They are never
interleaved:

- geopotential;
- specific humidity;
- temperature;
- eastward wind;
- northward wind; and
- pressure vertical velocity.

## Source and license

The source is the public WeatherBench2 ERA5 Zarr archive
`1959-2023_01_10-6h-240x121_equiangular_with_poles_conservative.zarr`. Its
exact `datasets/era5/LICENSE` object is the ECMWF Copernicus Licence to Use
Copernicus Products v1.2. It grants a free, worldwide, non-exclusive,
royalty-free, perpetual licence for any lawful purpose, expressly including
reproduction, distribution, adaptation, modification, and combination.

The recipe preserves the required adapted-product attribution:

> Contains modified Copernicus Climate Change Service information 2026.

Public use must also state that neither the European Commission nor ECMWF is
responsible for any use that may be made of the Copernicus information or data
it contains.

## Bounded selection

Eight deterministic source chunks per variable cover seasonal/decadal windows
from 1960 through 2022. Each Zarr chunk contains eight consecutive six-hour
analyses, producing 64 timestamps per series. The 48 selected source objects
total 459,101,417 compressed bytes.

The generated acquisition plan has SHA-256
`efa91f21a5db11f18712977d3dc550ff4aeca08a70b24ee175443aaa9ca75f8f`.
It pins every object name, GCS generation, compressed byte size, and MD5. The
consolidated Zarr metadata is independently pinned by SHA-256 and requires
native `<f4`, dimensions `[time, level, longitude, latitude]`, chunks
`[8, 13, 240, 121]`, and Blosc/LZ4 byte-shuffled compression.

## Decoding and verification

The self-contained Python decoder calls only the system `liblz4.so.1` through
`ctypes`; it requires no NumPy, xarray, Zarr, Blosc, or cloud SDK package. It
validates the Blosc header and block boundaries, expands each LZ4 byte lane,
reverses byte shuffle, and splits only the leading time dimension. Since the
source array is native little-endian float32, output bytes are copied unchanged
after decompression.

Build and verification passed on 2026-08-28. Independent verification
re-decoded all 48 compressed chunks and compared every emitted sample byte for
byte with its corresponding source time slice. It also confirmed:

- six series and exactly 64 unique timestamps per series;
- all 384 samples have shape `[13, 240, 121]`;
- all 144,967,680 values are finite and every sample is nonconstant;
- every output is little-endian IEEE-754 float32;
- source and output hashes, object identities, and aggregate totals agree; and
- no scaling, interpolation, regridding, transposition, or field interleaving
  occurred.
