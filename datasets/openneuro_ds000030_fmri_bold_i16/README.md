# OpenNeuro ds000030 fMRI BOLD Int16 — Discovery

This candidate targets complete four-dimensional functional-MRI BOLD runs from
OpenNeuro dataset `ds000030`. It is distinct from the accepted static T1w
structural-MRI family: each natural sample would preserve an entire spatial
volume time series.

The first stage is metadata-only. It:

- validates the official BIDS `dataset_description.json` as CC0;
- inventories public, non-derivative `*_bold.nii.gz` objects through the
  official OpenNeuro S3 listing;
- orders probes across tasks and subjects rather than taking one arbitrary
  directory slice;
- downloads at most a bounded compressed prefix from each probed object;
- parses the decompressed NIfTI-1 header without downloading voxel payloads;
- qualifies only rank-4 `datatype=4`, `bitpix=16`, identity-scaled images; and
- proposes a task/subject-diverse selection below 900 MB decoded output.

Run:

```bash
bash datasets/openneuro_ds000030_fmri_bold_i16/discover.sh
```

Results are written under
`.data/discovery/openneuro_ds000030_fmri_bold_i16/` and logs under
`.data/logs/openneuro_ds000030_fmri_bold_i16/`. No complete NIfTI object or
dataset payload is acquired during discovery.

Discovery qualified all 80 bounded header probes as little-endian rank-4
NIfTI-1 with native `datatype=4`, `bitpix=16`, and identity scaling. The pinned
selection retains ten different subjects, covers all eight available tasks,
and occupies 309,475,689 compressed bytes / 514,998,272 decoded bytes.

Acquire those exact ten CC0 objects:

```bash
bash datasets/openneuro_ds000030_fmri_bold_i16/download.sh
```

If native int16 runs qualify, a later build will preserve each complete 4D run
and serialize its unchanged stored voxel codes as canonical little-endian
signed-int16 values. It will not apply spatial masks, scaling, resampling,
normalization, or temporal concatenation.

After acquisition, build and verify locally:

```bash
bash datasets/openneuro_ds000030_fmri_bold_i16/build.sh
bash datasets/openneuro_ds000030_fmri_bold_i16/verify.sh
```

The ten complete runs contain 257,499,136 values / 514,998,272 primary bytes.
All have a 64×64×34 spatial grid, while their time axes range from 79 to 291
frames. Source voxel spacing is 3×3×4 mm and the repetition time is 2 seconds.
