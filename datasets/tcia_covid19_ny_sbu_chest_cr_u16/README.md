# TCIA COVID-19-NY-SBU portable chest radiographs (uint16, 12 bits stored)

48 complete portable AP chest X-ray images from TCIA's *Stony Brook University
COVID-19 Positive Cases* collection (COVID-19-NY-SBU), one image per distinct
patient. All come from one acquisition regime: Carestream DRX-Revolution
mobile unit, computed radiography (CR) modality, 0.139 mm imager pixel spacing,
and the full-field 2544 x 3056 matrix. Each sample is the complete DICOM Pixel
Data plane, copied byte for byte as little-endian uint16 (values 0-4095).

## What the numbers are

The values are the stored pixels of the archived clinical images. These are
vendor-processed "for presentation" radiographs (ImageType `DERIVED\PRIMARY`,
MONOCHROME2, identity rescale, PresentationLUTShape IDENTITY), not raw detector
frames. Zero-valued collimation borders are kept as stored. No windowing,
inversion, rotation, cropping or normalization is applied. All DICOM metadata
stays out of the samples.

Realized output from the 2026-10-05 build:

- 48 samples, 373,174,272 values, 746,348,544 bytes. Values span 0..4095.
- 47 of 48 planes reach 4095, but only on 18-59 pixels each. Overall, 3.0e-6
  of pixels are 4095, so this is not clipping.
- 2.4% of pixels are zero (collimation or shutter border). The highest
  per-image share is 24% (`chest_cr_19`).
- Per-image medians range from 1,550 to 2,705, and 99th percentiles from
  3,151 to 3,653.

A 1/16-scale montage confirms that all 48 are upright AP portable chest films.
Some show tubes, lines and electrodes; a few are slightly rotated or carry a
vendor shutter region. Standard technologist markers are burned into the
pixels: an L/R laterality letter, and text such as "PORTABLE" or "SITTING".
BurnedInAnnotation is NO, and TCIA applied its Clean Pixel Data option. No
identifiers were visible at that scale.

## Run

1. `bash staging/tcia_covid19_ny_sbu_chest_cr_u16/download.sh` (about 746.5 MB,
   48 GETs of about 15.55 MB each, plus 48 small metadata calls)
2. `bash staging/tcia_covid19_ny_sbu_chest_cr_u16/build.sh`
3. `bash staging/tcia_covid19_ny_sbu_chest_cr_u16/verify.sh`

Outputs:

- `samples/tcia_covid19_ny_sbu_chest_cr_u16/sbu_chest_cr_pixel_u16/chest_cr_NN.bin`:
  48 files of 15,548,928 bytes each (746,348,544 bytes total)
- `index/tcia_covid19_ny_sbu_chest_cr_u16/samples.jsonl`
- `filtered/tcia_covid19_ny_sbu_chest_cr_u16/ingest_stats.json`

## Selection

`pinned_series.tsv` fixes the 48 series. It records, per series: the series,
SOP, study and pseudonymous patient IDs, the file size, the header length and
the SHA-256 of the header bytes. `discover.sh` / `discover.py` document how
the pins were resolved and reproduce them. They fetch the ~9.9 MB NBIA CR
listing, so `download.sh` never runs them. The listing has 11,509 CR series;
the selection steps are:

1. Keep series that are CARESTREAM HEALTH DRX-REVOLUTION, CHEST, AP, one image
   each, CC BY 4.0, and whose StudyDesc starts with `CHEST AP ` and does not
   mention INFANT.
2. Restrict to the full-field size bucket: FileSize minus 15,548,928 pixel
   bytes must be 2-4 KB. Other buckets are collimation-cropped matrices.
   This leaves 3,089 series from 527 patients.
3. Take one series per patient: the smallest SeriesInstanceUID.
4. Order patients by `sha256("tcia_covid19_ny_sbu_chest_cr_u16:" + PatientID)`.
   Keep the first 48 whose live header validates exact Rows=2544 and
   Columns=3056. Six patients earlier in that order had 3056 x 2544 portrait
   objects in the same size bucket and were skipped.

The pinned images span software 5.7.712.6007 (39 images), .7009 (6) and
.8007 (3). Exposure is 90 kVp for 44 images and 76-98 kVp for the other 4.

## Validation

- `download.sh` checks the pin file's own SHA-256 first. It then re-checks
  each series' live NBIA row: license, collection, device, body part, view,
  ImageCount and FileSize. The server ignores Range and streams chunked
  responses, so each image is fetched whole into a `.part` file. The file is
  accepted only if it has the exact pinned size, header SHA-256 and pixel
  schema, and all values are 12-bit. The script records full-object SHA-256
  values in `download_inventory.json`.
- The stdlib parser (`scripts/cr_dicom.py`) walks Explicit VR Little Endian,
  including undefined-length sequences. It asserts: CR Image Storage,
  transfer syntax 1.2.840.10008.1.2.1, Rows 2544, Columns 3056, BitsAllocated
  16, BitsStored 12, HighBit 11, PixelRepresentation 0, MONOCHROME2, rescale
  0/1, LossyImageCompression `00`, BurnedInAnnotation `NO`, ImagerPixelSpacing
  0.139, and native OW Pixel Data of exactly 15,548,928 bytes as the final
  element. `selftest` exercises the parser on synthetic defined- and
  undefined-length sequence streams.
- `verify.sh` locates Pixel Data a second, independent way: the tail of the
  file must hold an exact OW element header. It cross-checks that offset
  against the header walker, byte-compares every sample, and recomputes every
  index row and statistic. It also checks distinct patients, duplicate
  planes, constant or low-cardinality planes, more-than-half-zero planes, and
  the manifest totals.

## License and attribution

The data is under CC BY 4.0, per the TCIA collection page and every NBIA
series row. Cite:

Saltz, J., Saltz, M., Prasanna, P., Moffitt, R., Hajagos, J., Bremer, E.,
Balsamo, J., & Kurc, T. (2021). Stony Brook University COVID-19 Positive Cases
[Data set]. The Cancer Imaging Archive. https://doi.org/10.7937/TCIA.BBAG-2923

This is sensitive de-identified clinical imaging. Follow the TCIA data usage
policy, and do not attempt re-identification or linkage.
