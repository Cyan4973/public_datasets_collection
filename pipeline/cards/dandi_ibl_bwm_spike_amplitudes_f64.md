# IBL Brain-Wide Map Neuropixels Spike-Sorted Unit Spike Amplitudes (DANDI:000409 units/spike_amplitudes_uV) Float64

- Candidate id: `dandi_ibl_bwm_spike_amplitudes_f64`
- Width: float64
- Quantity: Peak amplitude of each sorted spike in microvolts (NWB units/spike_amplitudes_uV, VectorData '<f8', ragged per unit via spike_amplitudes_uV_index), from IBL's standardized Neuropixels pipeline in mouse.
- Source: https://dandiarchive.org/dandiset/000409/0.260309.1324
- Resources: https://api.dandiarchive.org/api/dandisets/000409/versions/0.260309.1324/, https://api.dandiarchive.org/api/dandisets/000409/versions/0.260309.1324/assets/?glob=*processed*, https://api.dandiarchive.org/api/assets/388c82a6-94fe-4055-af61-4dfc05035633/download/, https://lindi.neurosift.org/dandi/dandisets/000409/assets/388c82a6-94fe-4055-af61-4dfc05035633/nwb.lindi.json
- License: CC-BY-4.0
- License evidence: https://api.dandiarchive.org/api/dandisets/000409/versions/0.260309.1324/
- License quote: Dandiset 000409 'IBL - Brain Wide Map' published version 0.260309.1324: "license": ["spdx:CC-BY-4.0"], access: dandi:OpenAccess, embargo_status OPEN.
- Natural record: One spike-sorted unit's complete spike-amplitude vector (slice of units/spike_amplitudes_uV between consecutive spike_amplitudes_uV_index entries), keeping units with at least 1,000 spikes. Mean is about 23k spikes per unit (20,667,745 spikes over 898 units in the probed session).
- Estimated samples: 2,200
- Estimated primary values: 55,000,000
- Estimated download bytes: 460,000,000
- Estimated primary bytes: 440,000,000
- Decode path: The processed NWB (HDF5, written with h5py) is read by byte-range GETs on the DANDI asset download URL (S3 redirect; ranges return 206). units/spike_amplitudes_uV is a chunked 1-D '<f8' dataset (chunks of 1,250,000) with a deflate filter (zlib level 4). Parse the HDF5 superblock, root group, /units group and the dataset's v1 chunk B-tree (the calo_hdf5.py precedent in datasets/zenodo_calochallenge_showers_f64 handles chunked deflate). Fetch only those chunks plus units/spike_amplitudes_uV_index ('<u4', 898), then zlib.decompress and struct '<d'. The LINDI JSON can serve as an independent cross-check of chunk offsets.
- Novelty kind: new_quantity
- Novelty evidence: novelty.py on the dandiset URL: no URL matches. No registry or ledger rows for 000409 or IBL. There are no 64-bit neuroscience families locally or downstream. Related local material is zenodo_npx_opto_templates_f32 (Kilosort template waveforms, a different quantity and width) and the queued 32-bit DANDI patch-seq and zebrafish-calcium candidates (different dandisets and quantities).
- Homogeneity: One pipeline (IBL pykilosort plus standardized NWB export), one quantity (per-spike peak amplitude, µV), one probe type (Neuropixels 1.0), one species. Suggest 2-3 complete sessions from different labs (e.g. first processed asset per lab in path order). Do not mix in spike_times, spike_distances_from_probe_tip_um (which is float32-exact) or the wheel series.
- Risks: Large per-session volume (about 165 MB of amplitudes per session), so the session count must be bounded explicitly. The amplitudes are derived from template fits rather than raw ADC, but they are pipeline-native float64 (0% float32-exact, and not a scaled float32). HDF5 navigation depth (NWB groups) adds builder work. I could not decode the per-unit spike-count index (LINDI blosc encoding), so the unit-count estimate is approximate. Processed files are 385-1185 MB, so range-fetching only the needed chunks is preferred over whole-file download.
- Probe evidence: DANDI API: published version license spdx:CC-BY-4.0, 459 *processed* NWB assets (385-1185 MB each). LINDI JSON for asset 388c82a6 lists units/spike_amplitudes_uV as '<f8' [20667745], chunks [1250000], zlib filter; the attribute description reads 'Peak amplitude of each spike for each unit in microvolts.' Range GET (206) of chunk 0 (offset 230,272,350, 9.29 MB compressed for 10 MB raw), partially decompressed: 40,192 values in range 68.9..1000.3 µV, 40,104 distinct, f32-exact 0.0, and not representable as float32 times 1e-6/1/1e-3/2.34375/0.195.

Proposed by the autocollect scout on 2026-10-05 (transcript `.data/pipeline/logs/scout_64bit/scout.20261005_215706.jsonl`).
