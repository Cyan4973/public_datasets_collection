# TCIA Eclipse RTDOSE UInt32

This recipe collects three de-identified abdominal radiotherapy dose
volumes from distinct studies in TCIA's `Pancreatic-CT-CBCT-SEG` collection.
The source objects are documented as Eclipse dose exports through Varian ARIA
and store physical planned dose as native unsigned 32-bit DICOM RTDOSE grids.

The recipe emits one natural 3D sample per RTDOSE object. It removes the DICOM
container but copies the complete Pixel Data field byte-for-byte; no dose
scaling is applied. `DoseGridScaling` is retained in the sample index as the
physical conversion factor.

Run:

```bash
bash datasets/tcia_eclipse_rtdose_u32/download.sh
bash datasets/tcia_eclipse_rtdose_u32/build.sh
bash datasets/tcia_eclipse_rtdose_u32/verify.sh
```
