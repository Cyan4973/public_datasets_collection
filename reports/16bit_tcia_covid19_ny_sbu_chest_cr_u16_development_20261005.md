# TCIA COVID-19-NY-SBU portable chest radiograph uint16 development

## Outcome

Accepted `tcia_covid19_ny_sbu_chest_cr_u16`: 48 complete portable anteroposterior chest X-ray images from TCIA's *Stony Brook University COVID-19 Positive Cases* collection (COVID-19-NY-SBU), one image per distinct patient. Each is emitted as its native DICOM Pixel Data plane: 12 bits stored in uint16, little-endian.

This is the corpus's first chest radiography family. The only local projection X-ray material is `tcia_cmmd_mammography_u16`, which has two mammography planes from a different anatomy, detector and SOP class. The LoDoPaB sinograms (`zenodo_lodopab_ct_sinograms_f32`) are simulated CT projections at float32. The sibling candidate `tcia_ldct_siemens_ct_projections_u16` is raw CT projection data, a different material.

## Source and rights

- Source: The Cancer Imaging Archive, COVID-19-NY-SBU, Version 1 (DateReleased 2021-08-11, status Complete). Accessed through the public anonymous NBIA REST API v1 (`getSeries`, `getSingleImage`).
- DOI: 10.7937/TCIA.BBAG-2923
- License: CC BY 4.0. The collection page lists Images, Clinical data and Template as CC BY 4.0. Every NBIA series row for the pinned objects reports LicenseName "Creative Commons Attribution 4.0 International License" and LicenseURI https://creativecommons.org/licenses/by/4.0/, and `download.sh` re-checks this per series.
- Citation: Saltz, J., Saltz, M., Prasanna, P., Moffitt, R., Hajagos, J., Bremer, E., Balsamo, J., & Kurc, T. (2021). Stony Brook University COVID-19 Positive Cases [Data set]. The Cancer Imaging Archive.
- Safety: the images are public, de-identified clinical data. Every header carries PatientIdentityRemoved YES and the DICOM PS3.15 Basic Profile with the Clean Pixel Data Option (113101), and dates are shifted. Only pixel values are emitted, and the TCIA data usage policy (no re-identification) applies.

## Shape and conversion

- Natural record: one complete single-image CR series, i.e. one radiograph, 2544 rows x 3056 columns = 7,774,464 values.
- Selection (`discover.py`, documentation only), applied to the NBIA CR listing of 11,509 series:
  - Filters: CARESTREAM HEALTH DRX-REVOLUTION, CHEST, AP, ImageCount 1, CC BY 4.0, StudyDesc `CHEST AP *` without INFANT, full-field size bucket. This leaves 3,089 series from 527 patients.
  - One series per patient (the smallest SeriesInstanceUID), with patients ordered by sha256(id-salted PatientID).
  - The first 48 with an exact 2544x3056 live header are pinned; six portrait-stored objects were skipped.
  - Pins carry FileSize, the Pixel Data offset and the header SHA-256. Full-object SHA-256 values are recorded in `download_inventory.json` and enforced by build and verify.
- Decode: a pure-stdlib Explicit VR Little Endian walker that handles defined- and undefined-length sequences. It asserts:
  - CR Image Storage, ImageType DERIVED\PRIMARY, AP, imager spacing 0.139 mm
  - pixel schema 1/2544/3056/16/12/11/0, MONOCHROME2, rescale 0/1, LossyImageCompression 00, PresentationLUT IDENTITY
  - native OW Pixel Data of exactly 15,548,928 bytes as the final element

  The bytes are copied unchanged in source row-major order. No windowing, inversion, rotation, cropping or metadata is applied or emitted.
- Material: these are vendor-processed "for presentation" archived pixels, not raw detector frames, and the manifest says so. Standard technologist markers are burned in (circled L, arrows, PORTABLE, AP, SUPINE, SEMI-SUPINE, ETT).

## Accepted output

- Primary samples: 48 (48 distinct patients, 48 unique plane SHA-256s)
- Primary values: 373,174,272
- Primary bytes: 746,348,544
- Sample size: 7,774,464 values (15,548,928 bytes) each; median the same
- Value range: 0..4095. Distinct values per image: 1,219-2,618
- Zero (collimation/shutter border) share: 2.39% overall; per image 0.07%-24.4%, median 0.36%
- Regime spread: SoftwareVersions 5.7.712.6007/.7009/.8007 = 39/6/3. KVP is 90 for 44 images; the other four are 76, 87, 95 and 98.
- DICOM download: 48 objects, 746,512,192 bytes, plus 48 small study-metadata JSON files

## Judge checks

- **Gate:** `gate.py` PASS with no warnings (48 samples, median 7,774,464 values, width 16).
- **verify.sh:** ran it myself. It passed (images=48, patients=48, range 0..4095) in 31 s.
- **Local-only build:** no network calls in `build.sh`, `verify.sh`, or the build/verify paths of `scripts/cr_dicom.py`. The pin file SHA-256 matches `download.sh`.
- **Independent header walk:** my own walker over all 48 DICOMs confirmed for each object:
  - 2544x3056, BitsStored 12, window 2048/4096
  - Pixel Data is the final OW element of 15,548,928 bytes
  - the sample is byte-identical to the file tail
  - DeID codes include 113101 (Clean Pixel Data Option)
- **Value distributions:** inspected samples 01, 07, 19, 25, 33 and 48 with `array('H')`.
  - Entropy is 8.6-10.5 bits per value and horizontal-delta entropy 7.0-8.9 bits. Low nibbles are near-uniform.
  - The 18 pixels per image at 4095 form a fixed glyph pattern, the burned-in L marker, not detector saturation.
  - 4080 is the annotation stroke value.
  - Per-image vendor tone-scale endpoints are populated, e.g. chest_cr_25 has 151,611 px at 3,336 and 81,665 px at 589.
- **Visual review:**
  - A 1/16-scale montage of all 48 shows distinct, genuine upright AP portable chest films.
  - I checked the annotation regions of all eight images with unique annotation-pixel counts (02, 08, 18, 30, 31, 34, 40, 47) at full resolution. They contain only positioning and device markers, no identifiers.
- **Rights:** opened the TCIA collection page (CC BY 4.0 for images, public, Complete). All 104 stored NBIA rows report CC BY 4.0. A credential scan of all scripts found nothing.
- **Novelty:** `novelty.py` on the NBIA and collection URLs, with collection, modality and device terms, found no chest radiography locally, in the registry or downstream.
- **Correction to the builder summary:** header ages actually span 26Y-87Y, not 33-76. No age range is claimed in the recipe files, and no demographics are emitted.
- **Size:** 746 MB is well above the ~100 MB downstream target but under the 1 GB cap. With 15.5 MB natural records, this is what meeting the 50-sample guidance costs; download and kept bytes are roughly 1:1.
