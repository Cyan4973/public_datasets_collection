# MorphoDunes PIV Float64 Vector Fields

This recipe extracts four paired two-dimensional velocity fields from the CC
BY 4.0 MorphoDunes laboratory PIV dataset on Zenodo record `16414450`.

Each MAT file stores matching `uPIV` and `vPIV` native float64 matrices on a
rectilinear grid. The recipe interleaves the two components cell by cell and
emits one `[y, x, component]` tensor per experiment. In MATLAB source order,
the x coordinate varies fastest, so this is a byte-order-preserving semantic
reshape plus component interleaving rather than interpolation or resampling.

The PIV software represents invalid or masked vectors with two signed quiet-NaN
encodings. They are part of the measured field geometry and are preserved
byte-exactly. Coordinate grids and the `zPIV` bed-profile vector are validated
as metadata but excluded from primary output.

Run from the repository root:

```bash
bash staging/zenodo_morphodunes_piv_f64/download.sh
bash staging/zenodo_morphodunes_piv_f64/build.sh
bash staging/zenodo_morphodunes_piv_f64/verify.sh
```

The pinned result contains four vector-field samples totaling 738,020 float64
values and 5,904,160 bytes. Of those values, 549,044 are finite measurements
and 188,976 are exact signed NaN mask cells.
