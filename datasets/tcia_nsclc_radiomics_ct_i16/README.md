# TCIA NSCLC Radiomics CT UInt16

Collects a bounded set of CT series from TCIA through the public NBIA API and emits one source DICOM pixel plane per slice.

The build accepts only uncompressed DICOM transfer syntaxes with
`BitsAllocated = 16`, `PixelRepresentation = 0`, `SamplesPerPixel = 1`,
and complete pixel payloads. Compressed DICOM, signed images, and non-16-bit
images are rejected.

```bash
SERIES_LIMIT=6 datasets/tcia_nsclc_radiomics_ct_i16/download.sh
datasets/tcia_nsclc_radiomics_ct_i16/build.sh
datasets/tcia_nsclc_radiomics_ct_i16/verify.sh
```
