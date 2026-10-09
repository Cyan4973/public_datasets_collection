# zenodo_minian_miniscope_v3_ca1_frames_u8

- Status: rejected
- Date: 2026-10-08
- Source: Zenodo record 20484805, "Minian demo data: Miniscope V3 Hippocampal CA1" (Daniel Aharoni, CC-BY-4.0, DOI 10.5281/zenodo.20484805)
- Resources: https://zenodo.org/api/records/20484805/files/msCam{1..10}.avi/content (10 x 72,203,510 B, md5-pinned)
- Attempted: a full recipe. The parser walks each AVI's structure, checks the header, the grey palette and that the codec is uncompressed, flips bottom-up rows to top-down, and emits one uint8 [200,480,752] sample per movie. Download, build, verify and gate.py passed in two runs (10 samples, 721,920,000 bytes, byte-identical builds, byte-exact second decode through the frame index).
- Failure: `zlsim.py gate` returned WEAK (redundant) both times. Run 1: nearest family `local:zenodo_nordif_ebsd_kikuchi_patterns_u8` at distance 0.0467, loss 0.0%. Run 2: the same family at distance 0.0486, loss −0.19%; next closest NOAA RSTN srs band B (0.0531, 3.69%) and downstream cov_hillshade (0.0571, −0.44%).
- Notes: the uploader decimated time 5x for Minian's test suite. Every movie uses the same 221 of 256 levels, with gaps every 7 or 8 codes, which points to a fixed linear contrast stretch applied before deposit. The record holds only 10 files, so no repair is possible.
- Evidence: .data/logs/zenodo_minian_miniscope_v3_ca1_frames_u8/{download,build,verify}.latest.log; /tmp/autocollect/zenodo_minian_miniscope_v3_ca1_frames_u8/zlsim_gate2.json (verdict WEAK, redundant=true)
