# UCI Steel Plates Faults Features Float64

Candidate recipe for industrial manufacturing quality-control features from the
UCI Steel Plates Faults dataset.

The target material is the numeric `Faults.NNA` table. Natural samples are one
source feature column over the preserved row order. The final seven fault-class
indicator columns are validation-only and are not emitted.

Run:

```bash
bash staging/uci_steel_plates_faults_features_f64/download.sh
```

Then build and verify locally:

```bash
bash staging/uci_steel_plates_faults_features_f64/build.sh
bash staging/uci_steel_plates_faults_features_f64/verify.sh
```
