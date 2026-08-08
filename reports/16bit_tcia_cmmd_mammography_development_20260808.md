# TCIA CMMD mammography uint16 development — 2026-08-08

## Outcome

Accepted `tcia_cmmd_mammography_u16`: two complete 2294×1914 native unsigned
16-bit mammography projection images from the TCIA Chinese Mammography
Database.

## Domain and shape distinction

This is the corpus's first mammography family. It adds large, sparse-background
two-dimensional projection X-rays, which differ materially from existing
tomographic CT slices, reconstructed PET volumes, and radiotherapy dose grids.
Each full DICOM image remains one natural sample; the images are not split into
artificial rows or patches.

## License-first discovery

TCIA metadata returned 1,775 CMMD mammography series, all declaring Creative
Commons Attribution 4.0. The downloaded archive also contains the exact CC BY
4.0 license text.

Metadata exposed a strong storage-width partition:

- 948 two-image series at 4,393,146 reported bytes per image
- 826 four-image series at 4,393,146 reported bytes per image
- one two-image outlier at 8,783,866 reported bytes per image

A representative normal-size probe proved native 8-bit pixels. The single
double-size outlier then proved to contain two native 16-bit images. Selection
therefore depended only on TCIA metadata and declared pixel width, not image
values or compression performance.

## Native type and decoding

Both selected DICOM objects have:

- Digital Mammography X-Ray Image Storage - For Presentation SOP class
- `MG` modality and Explicit VR Little Endian transfer syntax
- 2294 rows × 1914 columns
- one `MONOCHROME2` sample per pixel
- `BitsAllocated=16`, `BitsStored=16`, `HighBit=15`
- unsigned `PixelRepresentation=0`
- lossless status and left-image laterality
- exactly 8,781,432 Pixel Data bytes

The decoder validates exact DICOM hashes and schema, locates the one native
Pixel Data field, and copies its bytes unchanged. It applies no presentation
window, inversion, normalization, rescaling, cropping, or other transform.

## Accepted material

- 2 complete projection-image samples
- 4,390,716 uint16 values per image
- 8,781,432 total values
- 17,562,864 primary bytes
- stored range 0 through 65,535
- 901 distinct values in each image
- 832,111 and 889,502 adjacent-value transitions
- 7,089,529 zero-valued background pixels retained
- distinct source and output SHA-256 values

The low sample count is offset by the natural image size: each independently
decodable sample contributes 8.78 MB. Independent verification reparses the
exact source DICOM objects and compares every output byte, index row, and
aggregate statistic.

## Safety and exclusions

CMMD is de-identified human clinical mammography. The source DICOM objects
contain patient and study metadata, so the manifest conservatively marks the
family as personal and sensitive. Emitted samples contain only numeric Pixel
Data. Patient identifiers, study/series identifiers, dates, diagnoses,
demographics, and all other DICOM metadata are excluded from sample bytes.
