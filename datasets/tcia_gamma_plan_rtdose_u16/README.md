# TCIA GammaPlan RTDOSE UInt16

This recipe collects three de-identified radiotherapy dose volumes from
distinct studies in TCIA's `Vestibular-Schwannoma-SEG` collection. The source
objects were produced by Elekta GammaPlan and store physical planned dose as
native unsigned 16-bit DICOM RTDOSE grids.

The recipe emits one natural 3D sample per RTDOSE object. It removes the DICOM
container but copies the complete Pixel Data field byte-for-byte; no dose
scaling is applied. `DoseGridScaling` is retained in the sample index as the
physical conversion factor.

Run:

```bash
bash datasets/tcia_gamma_plan_rtdose_u16/download.sh
bash datasets/tcia_gamma_plan_rtdose_u16/build.sh
bash datasets/tcia_gamma_plan_rtdose_u16/verify.sh
```
