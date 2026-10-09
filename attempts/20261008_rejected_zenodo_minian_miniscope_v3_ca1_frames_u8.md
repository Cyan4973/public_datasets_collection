# zenodo_minian_miniscope_v3_ca1_frames_u8

- Status: rejected
- Date: 2026-10-08
- Source: Zenodo record 20484805, "Minian demo data: Miniscope V3 Hippocampal CA1" (Daniel Aharoni, CC-BY-4.0, DOI 10.5281/zenodo.20484805)
- Resources: https://zenodo.org/api/records/20484805/files/msCam{1..10}.avi/content (10 x 72,203,510 B, md5-pinned)
- Attempted: a full recipe. The parser walks each AVI's structure, checks the header, the 256-entry grey palette and that the codec is uncompressed, flips bottom-up rows to top-down, and emits one uint8 [200,480,752] sample per movie. Download, build, verify and gate.py all passed: 10 samples, 721,920,000 bytes, and a byte-exact second decode through the frame index.
- Failure: `zlsim.py gate` verdict WEAK (redundant). The nearest family, `local:zenodo_nordif_ebsd_kikuchi_patterns_u8`, sits at feature distance 0.0467 with 0.0% compression loss. Others: magellan_fmidr_sar_u8 (0.0569 distance, 0.55% loss), noaa_rstn srs band A (0.0606, 0.0%), blender video luma (0.065, 0.0%).
- Notes: the uploader decimated time 5x for Minian's test suite. Every movie uses the same 221 of 256 levels, with gaps every 7 or 8 codes, which points to a fixed linear contrast stretch applied before deposit. The record holds only 10 files.
- Evidence: .data/logs/zenodo_minian_miniscope_v3_ca1_frames_u8/{download,build,verify}.latest.log; zlsim gate JSON (verdict WEAK, redundant=true).
