# TCIA COVID-19-NY-SBU Carestream DRX-Revolution Portable Chest Radiographs (CR) Native 12-bit UInt16

- Candidate id: `tcia_covid19_ny_sbu_chest_cr_u16`
- Width: uint16
- Quantity: Projection radiography detector image: portable AP chest X-ray pixel values, 12 bits stored in uint16 (0-4095), MONOCHROME2, 0.139 mm imager pixel spacing, Carestream DRX-Revolution
- Source: https://www.cancerimagingarchive.net/collection/covid-19-ny-sbu/
- Resources: https://services.cancerimagingarchive.net/nbia-api/services/v1/getSeries?Collection=COVID-19-NY-SBU&Modality=CR, https://services.cancerimagingarchive.net/nbia-api/services/v1/getSOPInstanceUIDs?SeriesInstanceUID=<series>, https://services.cancerimagingarchive.net/nbia-api/services/v1/getSingleImage?SeriesInstanceUID=<series>&SOPInstanceUID=<sop>
- License: CC BY 4.0
- License evidence: https://www.cancerimagingarchive.net/collection/covid-19-ny-sbu/
- License quote: CT, CR, DX, MR, SR, NM, PT, OT DICOM Download (511.48gb) ... 1,384 7,361 17,950 562,376 CC BY 4.0 (each NBIA CR series row: LicenseName 'Creative Commons Attribution 4.0 International License', LicenseURI https://creativecommons.org/licenses/by/4.0/)
- Natural record: One complete CR radiograph (one single-image series), e.g. 2544 x 3056 = 7,774,464 uint16 pixels.
- Estimated samples: 48
- Estimated primary values: 373,174,272
- Estimated download bytes: 757,000,000
- Estimated primary bytes: 746,348,544
- Decode path: curl getSeries (CR, ~10.8 MB JSON), pin 48 series (one per distinct patient, DRX-REVOLUTION, CHEST, AP, canonical FileSize), then curl getSingleImage (or getImage zip) per series. The DICOM is Explicit VR Little Endian (1.2.840.10008.1.2.1), not compressed (LossyImageCompression 00). Walk tags with struct, skipping undefined-length sequences. Check Rows, Columns, BitsAllocated 16, BitsStored 12, PixelRepresentation 0, MONOCHROME2, rescale 1/0, then read Pixel Data with array('H').
- Novelty kind: new_source
- Novelty evidence: novelty.py found no term or registry hit for COVID-19-NY-SBU or radiograph. TCIA URL matches are other collections (CMMD MG, GammaPlan RTDOSE, Lung-PET-CT-Dx PT, NSCLC CT). Projection X-ray exists locally only as tcia_cmmd_mammography_u16, which has two mammography planes. Chest radiography is a different anatomy, detector and acquisition, and is absent at all widths locally and downstream.
- Homogeneity: Of 11,509 CR series, 11,092 are CARESTREAM DRX-REVOLUTION CHEST and 11,062 of those are AP. Restrict to that device, body part and view, plus one canonical size bucket (3,102 series at 15.54-15.57 MB, i.e. 2544x3056, from 527 patients), giving one regime of 12-bit portable chest radiographs. Exclude ABDOMEN, DRX-1, the PA/LATERAL views, and DX/CT/MR series.
- Risks: Images are vendor-processed 'for presentation' radiographs, not raw detector frames. Document them as the archived CR pixel data. Per-image download is ~15.5 MB. getSingleImage ignores Range headers, so a probe always pulls the whole image. COVID-positive clinical images are de-identified public TCIA data (BurnedInAnnotation NO), matching the precedent of the accepted TCIA recipes. Patient-level diversity: pick one image per patient. Two TCIA candidates are proposed this round, but they are different materials (raw CT projections vs radiographs).
- Probe evidence: getSeries?Modality=CR returned 12,660 rows, of which COVID-19-NY-SBU has 11,509 (1,343 patients, 176 GB, all CC BY 4.0). getSOPInstanceUIDs and getSingleImage were tried on one AP chest series; the server ignored the range and returned the full 15,552,410-byte DICOM, which was parsed and then deleted. TS 1.2.840.10008.1.2.1, 90 kVp, 2544x3056, BitsAllocated 16 / BitsStored 12 / HighBit 11, PixRep 0, MONOCHROME2, rescale 1/0, LossyCompr 00. Pixel range 0..4095 (p1 815, p50 2381, p99 3229). The collection page shows CC BY 4.0, Public, Complete.

Proposed by the autocollect scout on 2026-10-05 (transcript `.data/pipeline/logs/scout_16bit/scout.20261005_215706.jsonl`).
