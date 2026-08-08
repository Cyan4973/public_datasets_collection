# TCIA CMMD native uint16 mammography

This recipe extracts the two complete native unsigned-16-bit mammography Pixel
Data planes from CMMD's sole double-byte series outlier. Each source image is
2294×1914 and remains one natural high-resolution projection sample.

Run:

1. `bash datasets/tcia_cmmd_mammography_u16/download.sh`
2. `bash datasets/tcia_cmmd_mammography_u16/build.sh`
3. `bash datasets/tcia_cmmd_mammography_u16/verify.sh`

The dependency-free parser requires Digital Mammography X-Ray Image Storage
for Presentation, uncompressed Explicit VR Little Endian transfer syntax,
`BitsAllocated=16`, `BitsStored=16`, unsigned pixels, and exact geometry. It
copies Pixel Data byte-for-byte without windowing, inversion, normalization,
or rescaling. Exact DICOM hashes and the embedded CC BY 4.0 license are pinned.

The source is sensitive de-identified clinical imaging. Outputs contain only
numeric Pixel Data; all patient, study, date, diagnosis, demographic, and
other DICOM metadata is excluded.
