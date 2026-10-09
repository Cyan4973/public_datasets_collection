# DANDI:000488 Allen Institute OpenScope Predictive-Coding Two-Photon GCaMP ROI ΔF/F Traces (processing/ophys/dff/traces) Float64

- Candidate id: `dandi_000488_openscope_2p_dff_traces_f64`
- Width: float64
- Quantity: Per-ROI normalized fluorescence change (ΔF/F, unit 'Normalized fluorescence (A.U.)') from Allen pipeline two-photon calcium imaging at about 30 Hz in mouse V1, PM and retrosplenial cortex. Stored as native float64.
- Source: https://dandiarchive.org/dandiset/000488/0.230602.2022
- Resources: https://api.dandiarchive.org/api/dandisets/000488/versions/0.230602.2022/assets/?page_size=100, https://api.dandiarchive.org/api/assets/ab5ec054-8372-421c-a4f5-2cf53cf7e796/download/, https://lindi.neurosift.org/dandi/dandisets/000488/assets/ab5ec054-8372-421c-a4f5-2cf53cf7e796/nwb.lindi.json
- License: CC-BY-4.0
- License evidence: https://api.dandiarchive.org/api/dandisets/000488/versions/0.230602.2022/
- License quote: "license": ["spdx:CC-BY-4.0"]. I scanned the metadata for 'terms of use' and 'noncommercial' and found neither. That matters because sibling Allen dandisets such as 000039 add 'Data are subject to Allen Institute Terms of Use', which is why I did not choose them. Citation: Lecoq, Garrett, Choi, Mazzucato, Wyrick (2023), doi:10.48324/dandi.000488/0.230602.2022.
- Natural record: One sample is one ROI's complete session ΔF/F trace, about 115,600 frames (≈925 KB). The session frames x ROIs matrix also works, as in the accepted 001076 recipe. 42 of the 43 sessions have the dataset, with 17-356 ROIs each (about 5,200 ROIs in total). Suggested scope: about 8-12 whole sessions spread over distinct subjects, for roughly 450-550 ROI traces.
- Estimated samples: 500
- Estimated primary values: 57,800,000
- Estimated download bytes: 470,000,000
- Estimated primary bytes: 463,000,000
- Decode path: NWB HDF5 v0. processing/ophys/dff/traces/data is '<f8', shape [~115600, nROI], chunked by row blocks across all ROIs, with no filters (uncompressed). Use the IBL nwb_hdf5.py reader and BlockStore to resolve the chunk B-tree, then curl the exact chunk byte ranges (LINDI refs give the same offsets for a cross-check). Reassemble the matrix and emit each ROI column (or the matrix) bit-exact. Nothing needs inflating.
- Novelty kind: new_quantity
- Measurement type: calcium_roi_traces
- Instrument line: allen_brain_observatory_2p_rig
- Archive collection: dandiarchive.s3.amazonaws.com
- Novelty evidence: novelty.py --url https://dandiarchive.org/dandiset/000488 --terms OpenScope dF/F calcium: host-only match, no recipe from 000488. The calcium term hits are dandi_001076_zebrafish_calcium_fluorescence_f32 (raw Suite2p F at 32 bits), aind_bci_2p_scanimage_trials_i16 (movies, 16 bits) and a rejected u8 miniscope movie. 'calcium_roi_traces' exists only at width 32. No calcium or fluorescence family exists at 64. This is a different quantity (baseline-normalized ΔF/F from the Allen pipeline, not raw F) and a different lab and pipeline.
- Homogeneity: One quantity (ΔF/F), one pipeline (Allen Brain Observatory/OpenScope processing), one rig family, one stimulus paradigm. All sessions sample at about 30 Hz, with 115.5k-115.9k frames. Exclude calcium_events, raw and neuropil traces, and the behaviour series.
- Risks: (1) Breadth: the traces are noisy, full-precision f64 with mostly near-zero values plus sparse positive transients. That may or may not sit near an existing noisy f64 family in zlsim. (2) Allen dF/F can contain NaN in some sessions. Not seen in the probed rows, but build and verify need a missing-value policy. (3) One sample per ROI gives about 925 KB samples; whole-session matrices (17-150 MB) are also acceptable but coarser. (4) The judge may compare against the 32-bit zebrafish family on naming, but the gate compares within one width only.
- Probe evidence: I read the first ~3 MB (375,000 values) of the uncompressed dff chunk of sub-416366_ses-775204389 through LINDI ref offsets: 99.9997% distinct, 0% float32-exact, 0% integers, smallest gaps 5e-10, range -0.455..12.85, 15-19 significant digits. LINDI shapes for all 43 assets: [115558-115870, 17-356] '<f8' with no filters, missing in one asset (sub-440208_ses-20190313T174911). The DANDI asset download URL redirects to public S3 and range GETs work (same mechanism as the 000574 probe).

Proposed by the autocollect scout on 2026-10-09 (transcript `.data/pipeline/logs/scout_64bit/scout.20261009_004435.jsonl`).
