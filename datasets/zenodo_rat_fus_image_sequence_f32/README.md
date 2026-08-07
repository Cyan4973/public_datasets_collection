# Rat Functional-Ultrasound Image Sequence Float32

This recipe extracts one complete native little-endian float32 functional-
ultrasound intensity tensor from a CC BY 4.0 awake-rat experiment.

Run:

```bash
bash datasets/zenodo_rat_fus_image_sequence_f32/download.sh
bash datasets/zenodo_rat_fus_image_sequence_f32/inspect.sh
bash datasets/zenodo_rat_fus_image_sequence_f32/build.sh
bash datasets/zenodo_rat_fus_image_sequence_f32/verify.sh
```

The selected MATLAB v5 `I` array has logical shape
`187 image rows × 128 image columns × 4500 time frames`. The downloader
validates its exact matrix metadata and range-fetches only the source float32
field, excluding MATLAB framing and float64 timing arrays.
