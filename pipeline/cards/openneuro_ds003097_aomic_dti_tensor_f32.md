# AOMIC-ID1000 DTI Weighted-Least-Squares Diffusion-Tensor Fields Float32

- Candidate id: `openneuro_ds003097_aomic_dti_tensor_f32`
- Width: float32
- Quantity: Fitted diffusion-tensor elements (six unique components per voxel, diffusivity units of about 1e-3 mm^2/s) from weighted-least-squares DTI fits of eddy/topup-corrected 3T diffusion MRI, 2 mm isotropic voxels, brain-masked.
- Source: https://s3.amazonaws.com/openneuro.org/ds003097/derivatives/dwipreproc/
- Resources: https://s3.amazonaws.com/openneuro.org?list-type=2&prefix=ds003097/derivatives/dwipreproc/&delimiter=/&max-keys=1000, https://s3.amazonaws.com/openneuro.org/ds003097/derivatives/dwipreproc/sub-0001/dwi/sub-0001_model-DTI_desc-WLS_diffmodel.nii.gz, https://s3.amazonaws.com/openneuro.org/ds003097/derivatives/dwipreproc/sub-0001/dwi/sub-0001_model-DTI_desc-WLS_FA.nii.gz, https://s3.amazonaws.com/openneuro.org/ds003097/dataset_description.json
- License: CC0
- License evidence: https://s3.amazonaws.com/openneuro.org/ds003097/dataset_description.json
- License quote: "Name": "AOMIC-ID1000", "BIDSVersion": "1.0.2", "License": "CC0"
- Natural record: One participant's complete model-DTI_desc-WLS_diffmodel NIfTI volume: 112 x 112 x 60 x 6 float32 = 4,515,840 values (18,063,360 B).
- Estimated samples: 32
- Estimated primary values: 144,506,880
- Estimated download bytes: 125,000,000
- Estimated primary bytes: 578,027,520
- Decode path: Pure stdlib: download the .nii.gz with curl, decompress with zlib (wbits 31), and parse the NIfTI-1 348-byte header (dim int16[8] @40, datatype int16 @70 = 16, bitpix @72 = 32, vox_offset float @108 = 352, scl_slope/inter @112 = 1/0). Then read 4,515,840 little-endian float32 voxels (x fastest, then y, z, component) and emit them as one sample per participant.
- Novelty kind: new_quantity
- Novelty evidence: novelty.py --url .../ds003097/derivatives/dwipreproc/ --terms AOMIC ds003097 'diffusion tensor' DTI: the only hits are false-positive 'dti' substrings in nasa_donki_flr and usgs_fdsn_events_large. 'diffusion tractography' finds no matches. The local MRI families are ds000030 T1w f32 and ds000030 BOLD i16, and the downstream has openneuro_t1w_mri_f32. No diffusion/tensor family exists locally or downstream, and this is a different OpenNeuro dataset (AOMIC) from the ds000030 recipes.
- Homogeneity: One cohort (928 healthy adults, AOMIC-ID1000), one Philips 3T DWI protocol, and one preprocessing and WLS fit pipeline for all 925 participants with dwipreproc outputs. Dimensions (112,112,60,6) and float32 type were verified identical for sub-0001/0002/0300/0650/0928. All six components share one unit (diffusion tensor elements).
- Risks: The order of the six tensor elements isn't documented in a sidecar. The builder should verify the semantics by recomputing FA from the tensor and comparing it with the *_FA.nii.gz file. About 77% of voxels are exact zeros outside the brain mask. This is a fitted (derived) model product rather than raw acquisition, though it is the published native-float32 output. A second candidate (cortical thickness) comes from the same OpenNeuro dataset, via a different pipeline, file and quantity.
- Probe evidence: Range-read and gunzipped header of sub-0001 diffmodel: dim (4,112,112,60,6), pixdim 2 mm, datatype 16, bitpix 32, scl 1/0; the full 4,515,840 voxels decoded from a 4 MB range include 1,037,754 nonzero values from -0.0454 to 0.0455, with no integer-valued nonzeros. FA (112,112,60) is float32 from 0 to 1.207 with 172,959 nonzero values; preproc DWI (112,112,60,99) is float32 and genuinely floating-point. The S3 delimiter listing shows 925 sub-* prefixes under derivatives/dwipreproc (plus group_dwi.tsv). Headers of 4 more subjects returned HTTP 206 with identical dims. dataset_description.json reports License CC0.

Proposed by the autocollect scout on 2026-10-05 (transcript `.data/pipeline/logs/scout_32bit/scout.20261005_174424.jsonl`).
