# UCI Superconductivity Material Features Float64

Candidate recipe for materials-informatics numeric descriptors from the UCI
Superconductivity dataset.

The target material is the numeric `train.csv` table: elemental composition
descriptors and the `critical_temp` physical target. Natural samples are one
source CSV numeric column over the preserved row order. The formula table
`unique_m.csv` is not emitted.

Run:

```bash
bash staging/uci_superconductivity_material_features_f64/download.sh
```

Then build and verify locally:

```bash
bash staging/uci_superconductivity_material_features_f64/build.sh
bash staging/uci_superconductivity_material_features_f64/verify.sh
```
