# OpenNeuro ds000030 T1w MRI Float32

This recipe collects a bounded, exact selection of T1-weighted structural MRI
volumes from OpenNeuro dataset `ds000030`, the UCLA Consortium for
Neuropsychiatric Phenomics LA5c Study.

Metadata discovery verified:

- the dataset declares `CC0` in `dataset_description.json`;
- release DOI: `10.18112/openneuro.ds000030.v1.0.0`;
- 265 public BIDS `*_T1w.nii.gz` objects are available;
- `selection.tsv` pins the first 20 volumes by key, size, and S3 ETag/MD5.

The builder admits only complete 3D NIfTI-1 volumes with native float32
`datatype=16`, `bitpix=32`, identity scaling, finite values, valid payload bounds, and
nonconstant stored voxels. One complete T1w volume is one natural sample.
The source voxel order is preserved, with byte swapping only if a source is
big-endian.

Run:

```bash
bash datasets/openneuro_ds000030_t1w_mri_f32/download.sh
bash datasets/openneuro_ds000030_t1w_mri_f32/build.sh
bash datasets/openneuro_ds000030_t1w_mri_f32/verify.sh
```

`discover.sh` remains available to reproduce the metadata preflight; it does
not download MRI volumes.
