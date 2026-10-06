# DANDI:001076 Larval-Zebrafish Two-Photon Calcium-Imaging ROI Fluorescence Traces (Suite2p RoiResponseSeries) Float32

- Candidate id: `dandi_001076_zebrafish_calcium_fluorescence_f32`
- Width: float32
- Quantity: Per-ROI raw calcium fluorescence F (arbitrary units, float32) extracted by Suite2p from two-photon GCaMP imaging planes of larval zebrafish during optomotor-response experiments: a frames x ROIs matrix per imaging plane (e.g. 1,407 x 535 to 1,381 x 1,616)
- Source: https://dandiarchive.s3.amazonaws.com/dandisets/001076/draft/
- Resources: https://dandiarchive.s3.amazonaws.com/dandisets/001076/draft/dandiset.yaml, https://dandiarchive.s3.amazonaws.com/dandisets/001076/draft/assets.yaml, https://dandiarchive.s3.amazonaws.com/blobs/509/40a/50940a9d-a761-4475-94d9-a5467b03f531
- License: CC-BY-4.0
- License evidence: https://dandiarchive.s3.amazonaws.com/dandisets/001076/draft/dandiset.yaml
- License quote: description: 'Recorded calcium imaging data associated with the following manuscript: Embodied Neural Visuomotor Circuits in Neuromechanical Simulations and a Zebrafish Robot' ... license: - spdx:CC-BY-4.0 ... name: OMR Robot CaImaging
- Natural record: One imaging plane/session NWB file's processing/ophys/Fluorescence/RoiResponseSeries/data: a complete 2-D float32 (frames x ROIs) matrix written by Suite2p. Neuropil (Fneu) and Deconvolved (spike inference) series are different quantities and are excluded. image_mask/mean/correlation images (float64) are not primary.
- Estimated samples: 48
- Estimated primary values: 61,000,000
- Estimated download bytes: 660,278,264
- Estimated primary bytes: 245,000,000
- Decode path: Parse draft assets.yaml (48 ophys NWB assets, 660,278,264 B total), pin each blob URL plus its dandi:sha2-256, and curl -fL -C - then verify. Pure-stdlib HDF5 (superblock v0, symbol-table groups): navigate processing/ophys/Fluorescence/RoiResponseSeries/data, which is float32 LE with a single chunk equal to the full shape and the deflate filter only. Read the B-tree v1 type-1 node, zlib.decompress the one chunk, and emit as float32. Alternatively, range-fetch just the header blocks plus that chunk.
- Novelty kind: new_modality
- Novelty evidence: novelty.py --url on dandisets/001076/ and terms 'calcium imaging', 'suite2p', 'roiresponseseries', 'fluorescence trace' match nothing relevant. The only hit is zenodo_sanger_abif_i16 (DNA sequencing chromatogram 'fluorescence trace', unrelated). No optical-physiology / calcium-imaging family exists locally or downstream at any width. zenodo_rat_fus_image_sequence_f32 is functional ultrasound, a different modality.
- Homogeneity: One study, one microscope and indicator, one extraction pipeline (Suite2p RoiResponseSeries F), one quantity (raw ROI fluorescence, a.u.), roughly the same frame count per plane (about 1,381-1,407). Only F is kept; Neuropil and Deconvolved are excluded so no regimes are mixed.
- Risks: (1) The dandiset is draft-only (no published version). Blob URLs are content-addressed and immutable and assets.yaml carries sha256 digests, so pin those. (2) Modest volume (about 245 MB primary, 48 samples; estimated from a 0.35-0.40 F-to-file-size ratio on two files). (3) Suite2p F is a pinned machine-facing derived product (comparable to the accepted Kilosort templates), not raw movies, which this dandiset does not include. (4) Neuroscience again (zebrafish); breadth-wise it is the third neuro-adjacent proposal behind four accepted OpenNeuro families. (5) Subject IDs are 'sub-nan'; the 48 files are distinct imaging objects (several per session), which the builder should confirm are not duplicates (distinct sha256 already).
- Probe evidence: dandiset.yaml (draft): license spdx:CC-BY-4.0, name 'OMR Robot CaImaging'. Draft assets.yaml: 48 NWB files, 8.6-22.1 MB each, 660,278,264 B total, no published version folder in the bucket listing. A one-byte -L range GET on blob 50940a9d-... returned 206. HDF5 walk (about 0.7 MB of header ranges): superblock v0; processing/ophys/Fluorescence/{RoiResponseSeries, Neuropil, Deconvolved}/data each float32LE (1407, 535), one chunk, deflate. ImageSegmentation has 535 ROIs over a 270x292 plane. Another file has (1381, 1616). Decoding the full RoiResponseSeries chunk (2,617,711 B compressed, 752,745 values) gave range -28.7..569.1, 736,226 distinct values: genuinely continuous float32.

Proposed by the autocollect scout on 2026-10-05 (transcript `.data/pipeline/logs/scout_32bit/scout.20261005_194855.jsonl`).
