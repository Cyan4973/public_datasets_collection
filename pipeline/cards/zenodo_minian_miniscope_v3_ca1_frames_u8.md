# UCLA Miniscope V3 One-Photon GCaMP6f Hippocampal CA1 Raw Calcium-Imaging Movies (msCam AVI, 752x480, uncompressed 8-bit) UInt8

- Candidate id: `zenodo_minian_miniscope_v3_ca1_frames_u8`
- Width: uint8
- Quantity: Raw one-photon epifluorescence sensor intensity (8-bit gray level) of GCaMP6f-expressing mouse hippocampal CA1 neurons, imaged through a head-mounted UCLA Miniscope V3 CMOS sensor; 200 frames per file (the upload is temporally downsampled 5x).
- Source: https://zenodo.org/records/20484805
- Resources: https://zenodo.org/api/records/20484805, https://zenodo.org/api/records/20484805/files/msCam1.avi/content, https://zenodo.org/api/records/20484805/files/msCam10.avi/content
- License: CC-BY-4.0
- License evidence: https://zenodo.org/api/records/20484805
- License quote: metadata.license = {'id': 'cc-by-4.0'} (Zenodo record 20484805, 'Minian demo data: Miniscope V3 Hippocampal CA1', published 2026-06-01)
- Natural record: One msCam*.avi movie file: 200 frames x 480 rows x 752 cols of 8-bit gray pixels (72,192,000 values).
- Estimated samples: 10
- Estimated primary values: 721,920,000
- Estimated download bytes: 722,035,100
- Estimated primary bytes: 721,920,000
- Decode path: Pure-stdlib RIFF/AVI walk. avih is 752x480 with 200 frames; strf BITMAPINFOHEADER has biCompression=0 (BI_RGB), biBitCount=8, biSizeImage=360960, plus a verified identity gray palette. The movi LIST holds '00dc' chunks of 360,960 bytes; emit them in order and handle bottom-up DIB rows. Reject a file on wrong frame size, non-zero codec, or non-identity palette. Pin the Zenodo md5 values.
- Novelty kind: new_modality
- Measurement type: calcium_imaging_movie
- Instrument line: ucla_miniscope_v3_cmos
- Archive collection: zenodo.org
- Novelty evidence: novelty.py --url https://zenodo.org/records/20484805 --terms miniscope minian one-photon msCam returns zero term matches in any layer; the URL match is host-only. No one-photon miniscope raw movie exists at any width. The nearest families are calcium_roi_traces (f32 traces) and twophoton_movie (i16).
- Homogeneity: Single session, single Miniscope V3 sensor and settings. All 10 files have identical geometry and byte size, and one generation process.
- Risks: Only 10 files: this is the complete scope, but below the ~20 soft target; the judge may count frames instead (2,000). The 5x temporal decimation was done by the uploader. Zenodo host-count sign-off rule applies. Possible zlsim proximity to blender video luma.
- Probe evidence: Zenodo API lists 10 files of 72,203,510 B each with md5. A 16 KB range GET of msCam1.avi gave RIFF AVI, avih 752x480, 200 frames; strf 8bpp BI_RGB with 360960-byte frames and an identity gray palette; the first chunk is '00dc' of 360,960 B, with values ~100-110.

Proposed by the autocollect scout on 2026-10-08 (transcript `.data/pipeline/logs/scout_8bit/scout.20261008_162656.jsonl`).
