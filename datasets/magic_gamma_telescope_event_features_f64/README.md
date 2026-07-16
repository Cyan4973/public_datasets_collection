# MAGIC Gamma Telescope Event Features Float64

Candidate recipe for Cherenkov telescope event-image features from the UCI MAGIC
Gamma Telescope dataset.

The target material is the ten numeric event parameters from `magic04.data`.
The gamma/hadron class label is not emitted. Natural samples are one source
feature column over the preserved row order.

Run:

```bash
bash staging/magic_gamma_telescope_event_features_f64/download.sh
```

Then build and verify locally:

```bash
bash staging/magic_gamma_telescope_event_features_f64/build.sh
bash staging/magic_gamma_telescope_event_features_f64/verify.sh
```
