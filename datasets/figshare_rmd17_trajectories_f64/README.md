# Revised MD17 molecular trajectories — float64

This draft targets five molecules from version 3 of the revised MD17 dataset:

- aspirin
- benzene
- ethanol
- malonaldehyde
- toluene

For each molecule it emits two native NumPy float64 tensors in source order:
atomic coordinates and atomic forces, both shaped
`configuration × atom × xyz`.

The recipe fails closed unless the NPZ members declare C-order little-endian
float64 arrays and coordinates/forces have identical three-dimensional shapes.
It does not widen float32 arrays.

Source record: <https://doi.org/10.6084/m9.figshare.12672038.v3>

The pinned Figshare record is released under CC0. The downloader validates that
license metadata and selects either direct NPZ files or the official rMD17
archive. It prints and records the realized file plan before downloading.

## Run

```bash
bash datasets/figshare_rmd17_trajectories_f64/download.sh
bash datasets/figshare_rmd17_trajectories_f64/build.sh
bash datasets/figshare_rmd17_trajectories_f64/verify.sh
```

If Figshare's versioned inventory no longer contains the expected molecule
files, the downloader stops without accepting substitute material.
