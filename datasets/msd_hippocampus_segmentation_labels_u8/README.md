# MSD Hippocampus Segmentation Labels UInt8

This staged recipe collects the Medical Segmentation Decathlon Task04
Hippocampus archive and emits one `uint8` 3D segmentation-label volume per
training label file.

Defaults:

```sh
MSD_HIPPOCAMPUS_URL=https://msd-for-monai.s3-us-west-2.amazonaws.com/Task04_Hippocampus.tar
MSD_HIPPOCAMPUS_LICENSE_URL=https://msd-for-monai.s3-us-west-2.amazonaws.com/license.txt
MSD_HIPPOCAMPUS_MAX_FILE_BYTES=100000000
MSD_HIPPOCAMPUS_MAX_LABELS=0
```

`MSD_HIPPOCAMPUS_MAX_LABELS=0` means keep every qualifying `labelsTr/*.nii.gz`
label volume in the archive. Set it to a positive integer for a bounded subset.

Usage after the user-run external download:

```sh
bash staging/msd_hippocampus_segmentation_labels_u8/download.sh
bash staging/msd_hippocampus_segmentation_labels_u8/build.sh
bash staging/msd_hippocampus_segmentation_labels_u8/verify.sh
```

The build reads NIfTI-1 single-file `.nii.gz` label volumes from the tar archive
using Python stdlib only. It accepts integer NIfTI payloads whose class IDs fit
in `uint8`, writes the label codes as raw bytes, and rejects image intensity
volumes, non-3D labels, scaled labels, constant labels, and unsupported NIfTI
datatypes.
