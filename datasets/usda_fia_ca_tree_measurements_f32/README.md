# USDA FIA California Tree Measurements Float32

Candidate recipe for tree-level forestry inventory measurements from the USDA
Forest Inventory and Analysis DataMart.

The target source is California's FIA `TREE` table ZIP. Natural samples are one
numeric measurement field over the preserved source row order. Identifier, code,
and label-like columns are excluded; retained fields are measurement families
such as diameter, height, stocking, biomass, carbon, and volume.

Run:

```bash
bash staging/usda_fia_ca_tree_measurements_f32/download.sh
```

Then build and verify locally:

```bash
bash staging/usda_fia_ca_tree_measurements_f32/build.sh
bash staging/usda_fia_ca_tree_measurements_f32/verify.sh
```
