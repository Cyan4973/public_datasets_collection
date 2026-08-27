# NASA WMAP HEALPix Sky Maps Float32

This recipe targets the official NASA/LAMBDA WMAP nine-year K, Ka, Q, V,
and W band Stokes I/Q/U sky maps.

This numeric structure is new to the accepted corpus: each field is a
complete equal-area HEALPix sphere in its published pixel ordering, rather
than a rectangular raster, catalog column, time series, or interferometric
visibility sequence. Temperature and the Q/U polarization components will be
separate homogeneous samples; they will never be interleaved.

The optional discovery step is deliberately metadata-only. It captures official WMAP and
NASA rights pages, probes at most 64 KiB from each expected FITS object, and
reports:

- whether all five frequency-band products are directly reachable;
- the exact remote size and final URL;
- FITS binary-table column names and `TFORM` storage types;
- HEALPix `NSIDE`, ordering, coordinate system, and value count;
- whether the temperature/Q/U fields are native float32 (`E`).

Run from the repository root:

```bash
bash datasets/nasa_wmap_healpix_sky_maps_f32/discover.sh
```

No complete sky map is downloaded by this step. Discovery confirmed that all
five files are directly reachable, each is 100,676,160 bytes, and the first
extension contains 3,145,728 `NESTED` HEALPix rows with four scalar `E`
columns: `TEMPERATURE`, `Q_POLARISATION`, `U_POLARISATION`, and `N_OBS`.

Download the five exact files (503,380,800 bytes total), capture the official
provenance/rights pages, and run the local full-file preflight with:

```bash
bash datasets/nasa_wmap_healpix_sky_maps_f32/download.sh
```

The preflight inventories every HDU and profiles the four Stokes-map columns
plus the `QQ`, `QU`, and `UU` polarization-weight columns independently. The
second extension's repeated `N_OBS` field must be byte-identical to the first
extension and is counted only once. It does not emit training samples.

The accepted output contains seven field families across five frequency bands:
temperature, Q and U polarization, effective observation count, and the QQ,
QU, and UU polarization-weight elements. The 35 samples each contain 3,145,728
values. Total primary material is 110,100,480 float32 values, or 440,401,920
bytes. Every source and output value is finite, non-sentinel, and nonconstant.
