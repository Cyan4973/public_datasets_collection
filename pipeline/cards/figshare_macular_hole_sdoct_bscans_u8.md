# Longitudinal SD-OCT Retinal B-Scans of Macular-Hole Surgery Patients (750x500, gray plane of LZW TIFFs) UInt8

- Candidate id: `figshare_macular_hole_sdoct_bscans_u8`
- Width: uint8
- Quantity: Spectral-domain OCT reflectivity (8-bit gray level) of the human macula in H/V B-scans, preoperative to 48 months after macular-hole surgery.
- Source: https://figshare.com/articles/dataset/Pixel-Level_Segmented_Longitudinal_Optical_Coherence_Tomography_Data_of_Macular_Hole_Surgery_Outcomes/32605218
- Resources: https://api.figshare.com/v2/articles/32605218, https://ndownloader.figshare.com/files/65374524
- License: CC-BY-4.0
- License evidence: https://api.figshare.com/v2/articles/32605218
- License quote: license: {'value': 1, 'name': 'CC BY 4.0', 'url': 'https://creativecommons.org/licenses/by/4.0/'}
- Natural record: One B-scan TIFF of 750 x 500; the gray plane gives 375,000 values.
- Estimated samples: 2,591
- Estimated primary values: 971,625,000
- Estimated download bytes: 1,112,000,000
- Estimated primary bytes: 971,625,000
- Decode path: Download Dataset.zip (or range-fetch the *_OCT/*.tiff members via the zip64 central directory) and inflate with zlib. TIFFs are LE single-strip 750x500 RGBA 8-bit, LZW with predictor 2 (59 are uncompressed). Decode with a stdlib LZW decoder plus predictor undo, emit the R plane, verify R==G==B for >=99.9% of pixels, and skip the mask PNGs.
- Novelty kind: new_modality
- Measurement type: oct_bscan
- Instrument line: clinical_sd_oct_retina
- Archive collection: figshare.com
- Novelty evidence: novelty.py with terms optical coherence / OCT / retinal / macular hole finds no relevant match in any layer; the URL match is host-only. No OCT or ophthalmic imaging type exists in the vocabulary.
- Homogeneity: One study and one device/export pipeline. All probed members are 750x500 RGBA 8-bit with identical tags. Seven timepoints of the same scan protocol, H and V orientations.
- Risks: Viewer export (gray as RGBA) with ~0.04% non-gray pixels: disclose or filter. Taking all scans is near the 1 GB cap, so a subset is possible. Possible zlsim proximity to HC18 ultrasound. An older figshare version exists (30648086); pin 32605218 / file 65374524.
- Probe evidence: Zip64 central directory read by range GET: 5,213 entries including 2,591 tiffs (1.18 GB uncompressed). One 437 KB member was inflated and decoded: 750x500, spp4, LZW+pred2, gray fraction 0.99956, 225 levels, layered retina visible. A baseline member has identical tags.

Proposed by the autocollect scout on 2026-10-08 (transcript `.data/pipeline/logs/scout_8bit/scout.20261008_162656.jsonl`).
