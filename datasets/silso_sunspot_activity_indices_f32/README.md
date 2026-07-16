# SILSO Sunspot Activity Indices Float32

Candidate recipe for solar activity index time series from the SILSO World Data
Center.

The target resources are the daily and monthly total sunspot-number CSV files.
Natural samples are one cadence-field series: sunspot number, standard
deviation, and observation count for each cadence. Calendar columns and
definitive/provisional flags are not emitted.

Run:

```bash
bash staging/silso_sunspot_activity_indices_f32/download.sh
```

Then build and verify locally:

```bash
bash staging/silso_sunspot_activity_indices_f32/build.sh
bash staging/silso_sunspot_activity_indices_f32/verify.sh
```
