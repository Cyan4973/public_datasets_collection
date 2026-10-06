# Boreas Applanix POSPac SBET Post-Processed GNSS/INS Navigation Records Float64

- Candidate id: `boreas_applanix_sbet_navigation_f64`
- Width: float64
- Quantity: Applanix SBET (Smoothed Best Estimate of Trajectory) 17-double records at 200 Hz from the Boreas research vehicle (Toronto, 2020-2021). Fields: GPS seconds-of-week, latitude and longitude (rad), ellipsoidal altitude (m), x/y/z velocity (m/s), roll/pitch/platform heading/wander (rad), x/y/z body acceleration (m/s²), x/y/z angular rate (rad/s). It is the native headerless little-endian float64 instrument output.
- Source: https://boreas.s3.amazonaws.com/
- Resources: https://boreas.s3.amazonaws.com/?list-type=2&delimiter=/, https://boreas.s3.amazonaws.com/boreas-2020-11-26-13-58/applanix/sbet.out, https://boreas.s3.amazonaws.com/boreas-2021-01-15-12-17/applanix/sbet.out, https://boreas.s3.amazonaws.com/boreas-2021-11-02-11-16/applanix/sbet.out, https://github.com/utiasASRL/pyboreas/blob/master/DATA_LICENSE.md
- License: UNVERIFIED (license gate must be cleared first)
- License evidence: https://github.com/utiasASRL/pyboreas/blob/master/DATA_LICENSE.md
- License quote: UNVERIFIED. Web search shows a DATA_LICENSE.md in the official pyboreas devkit, but github.com is unreachable from the scout network. A third-party card (huggingface.co/datasets/Voxel51/boreas-multimodal, 2026-08) states: "License: Unknown — the AWS Open Data Registry listing's License field is blank, and no license is stated in the pyboreas devkit or bucket contents at the time of this card". Neither Boreas paper (arXiv 2203.10168, 2602.16870) states a data license.
- Natural record: One drive sequence's applanix/sbet.out: N×17 float64 records of 136 bytes, about 225k-905k records (19-75 min at 200 Hz).
- Estimated samples: 13
- Estimated primary values: 70,000,000
- Estimated download bytes: 563,000,000
- Estimated primary bytes: 563,000,000
- Decode path: 1. curl each pinned sbet.out (one sequence per calendar month, 2020-11 to 2021-11). 2. Check size % 136 == 0 (true for all 35 listed files). 3. Decode each record with struct.unpack('<17d') and validate: lat/lon in radians within Toronto bounds, finite values, monotone GPS seconds-of-week. 4. Emit the decoded records row-major. The output equals the source doubles, a typed record array rather than container bytes.
- Novelty kind: new_source
- Novelty evidence: `novelty.py --url https://boreas.s3.amazonaws.com/ --terms boreas sbet applanix` returns no matches in recipes, registry, ledger or downstream. No local or downstream family carries a GNSS/INS post-processed navigation solution; TUM RGB-D pose is indoor mocap.
- Homogeneity: One instrument record type (Applanix SBET), one vehicle, one post-processing chain, and a fixed 200 Hz lattice. The record mixes units across its 17 fields, as in the accepted tum_rgbd translation+quaternion matrices. If a judge objects, narrow it to the position triple (lat, lon, alt). Exclude the 2022-08-05 sequences (four byte-identical 258 MB files) and 'sbet_Mission 1.out'.
- Risks: 1. License is unverified, a likely reject unless DATA_LICENSE.md is permissive; the screener should check it before any build work. 2. The mixed-unit record could draw a homogeneity objection. 3. A large primary (~563 MB). 4. sbet.out covers pre- and post-roll beyond the sequence window.
- Probe evidence: Root ListObjectsV2 shows 126 prefixes (121 sequences). Per-sequence listing found sbet.out in 35 sequences (2020-11 to 2022-08), all sizes multiples of 136 B (30.4-123.1 MB for 2020-2021). Range-GET of the first 680 bytes of boreas-2020-11-26-13-58/applanix/sbet.out decoded as 5 records, e.g. t=413741.0563, lat=0.7641383538 rad (43.7819°), lon=-1.38691321 rad (-79.4643°), alt=153.578 m, followed by velocity, attitude, acceleration and angular-rate fields.

Proposed by the autocollect scout on 2026-10-05 (transcript `.data/pipeline/logs/scout_64bit/scout.20261005_174424.jsonl`).
