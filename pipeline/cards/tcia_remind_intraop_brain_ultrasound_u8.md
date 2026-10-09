# ReMIND Brain-Resection Intraoperative 3D Ultrasound Volumes (US_pre_dura sweeps, uncompressed 8-bit DICOM) UInt8

- Candidate id: `tcia_remind_intraop_brain_ultrasound_u8`
- Width: uint8
- Quantity: Intraoperative 3D B-mode ultrasound echo intensity (8-bit gray level) of the brain and tumour during neurosurgical resection, from reconstructed tracked-sweep volumes.
- Source: https://doi.org/10.7937/3RAG-D070
- Resources: https://services.cancerimagingarchive.net/nbia-api/services/v1/getSeries?Collection=ReMIND&Modality=US, https://services.cancerimagingarchive.net/nbia-api/services/v1/getSOPInstanceUIDs?SeriesInstanceUID=1.3.6.1.4.1.14519.5.2.1.49967757988005647898212263882068490488, https://services.cancerimagingarchive.net/nbia-api/services/v1/getSingleImage?SeriesInstanceUID=<series>&SOPInstanceUID=<sop>
- License: CC-BY-4.0
- License evidence: https://api.datacite.org/dois/10.7937/3RAG-D070
- License quote: DataCite rightsList: 'Creative Commons Attribution 4.0 International' (cc-by-4.0); all 320 NBIA US series rows carry LicenseName 'Creative Commons Attribution 4.0 International License'
- Natural record: One US series = one single-file multiframe DICOM volume, e.g. 135 x 607 x 793 (64,982,385 values).
- Estimated samples: 13
- Estimated primary values: 950,000,000
- Estimated download bytes: 960,000,000
- Estimated primary bytes: 950,000,000
- Decode path: NBIA getSeries discovers the US_pre_dura series (104 of them); select deterministically by PatientID up to ~950 MB. getSOPInstanceUIDs then getSingleImage returns a raw Part-10 DICOM. A stdlib explicit-VR LE tag walk (TS 1.2.840.10008.1.2.1) checks BitsAllocated=8, MONOCHROME2, spp 1; emit the native OB PixelData of rows*cols*frames bytes and reject anything else.
- Novelty kind: new_source
- Measurement type: ultrasound_volume
- Instrument line: amigo_intraop_tracked_3d_us
- Archive collection: services.cancerimagingarchive.net/nbia-api
- Novelty evidence: novelty.py on the DOI with terms ReMIND intraoperative ultrasound brain finds no ReMIND match. The only 8-bit ultrasound family is HC18 2D fetal B-mode (verdict OK); this candidate is a new source, anatomy and 3D reconstruction. tcia_breast_lesions_usg_u8 was blocked only because that collection is absent from NBIA; ReMIND is live.
- Homogeneity: One collection and protocol, one PixelMed NRRDToDicom conversion, one sweep stage (pre-dura). All volumes are 8-bit MONOCHROME2 with slope 1 and intercept 0. Dimensions vary naturally per sweep.
- Risks: Possible zlsim proximity to HC18 ultrasound. Large zero background outside the sweep (fill-dominance check). Only ~13 volumes fit under the cap. De-identified human clinical data. Large per-file fetches need resumable curl.
- Probe evidence: NBIA lists 320 ReMIND US series (114 patients, 23.1 GB), all CC BY 4.0. The first 64 KB of one getSingleImage parsed as TS explicit LE, US, frames 135, 607x793, bits 8/8, pixrep 0, PixelData length 64,982,386 OB.

Proposed by the autocollect scout on 2026-10-08 (transcript `.data/pipeline/logs/scout_8bit/scout.20261008_162656.jsonl`).
