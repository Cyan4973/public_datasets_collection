# Svalbard Glacier Ground-Penetrating Radar Int16

This recipe extracts 12 native little-endian signed-int16 MALA ProEx RD3
radargrams from a CC BY 4.0 snow-depth survey over Svalbard glaciers.

Run:

```bash
bash datasets/zenodo_gpr_rd3_i16/download.sh
bash datasets/zenodo_gpr_rd3_i16/inspect.sh
bash datasets/zenodo_gpr_rd3_i16/build.sh
bash datasets/zenodo_gpr_rd3_i16/verify.sh
```

Each output is one complete survey transect with shape
`survey trace × 1,024 two-way-travel-time samples`. The source `.rad` control
file declares `SHORT FLAG:1`, and the complete `.rd3` payload is copied without
conversion or reordering.
