# Terra MODIS 8-day active-fire mask (u8)

Accepted recipe for source-native MOD14A2 Collection 6.1 active-fire mask
class grids. It fixes four MODIS sinusoidal tiles spanning western North
America, the Amazon basin, southern Africa, and Australia at three 2024 8-day
composite start dates. Every natural sample is a complete 1,200 by 1,200
single-band `uint8` FireMask grid.

The build preserves all primary-resolution class codes without cropping,
resampling, remapping, or concatenating source records. The twelve samples are
fixed-size and total 17,280,000 bytes.

## License

The collection's license link points to the official LP DAAC data-policy page,
which states that unmarked data from NASA-led missions are CC0 with no use
restrictions. MOD14A2 identifies NASA LP DAAC as producer/licensor and carries
no separate product-specific restriction. Retain the MOD14A2.061 DOI, NASA/LP
DAAC attribution, collection version, exact item IDs, and dates.

## Run

From the repository root:

```bash
bash datasets/modis_active_fire_mask_u8/download.sh
bash datasets/modis_active_fire_mask_u8/build.sh
bash datasets/modis_active_fire_mask_u8/verify.sh
```

The downloader uses a short-lived Planetary Computer access token and never
prints it. The build uses only Python's standard library and strictly validates
the proven classic-TIFF, Deflate, tile, type, shape, class, and diversity
invariants.

## Investigation probes

The earlier metadata/header-only access probe can be rerun with:

Run from the repository root:

```bash
bash staging/modis_active_fire_mask_u8/probe_planetary_computer.sh
```

Its durable log is:

```text
.data/logs/modis_active_fire_mask_u8/planetary_computer_probe.latest.log
```

The fixed source-discovery probe is:

```bash
bash staging/modis_active_fire_mask_u8/discover_selection.sh
```

This second probe performs STAC metadata searches only. It selects the Terra
MOD14A2 8-day `FireMask` for four fixed tiles (western North America, the
Amazon basin, southern Africa, and Australia) at three fixed 2024 seasonal
dates. It requires exactly twelve single-band native `uint8` assets and writes
the exact item IDs and URLs to the ignored local discovery directory. Its log
is:

```text
.data/logs/modis_active_fire_mask_u8/selection_discovery.latest.log
```

Temporary SAS token responses are stored under a mode-700 ignored data
directory and are never printed or committed.
