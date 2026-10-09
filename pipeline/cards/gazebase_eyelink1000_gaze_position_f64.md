# GazeBase (Texas State) EyeLink 1000 Monocular 1 kHz Gaze Position in Degrees of Visual Angle, Float64

- Candidate id: `gazebase_eyelink1000_gaze_position_f64`
- Width: float64
- Quantity: Horizontal and vertical gaze position of the left eye (x, y), in degrees of visual angle. Recorded with an SR Research EyeLink 1000 at 1,000 Hz during seven oculomotor tasks: fixation, horizontal saccades, random saccades, reading, two video free-viewing tasks and a gaze-driven game. Emit gaze_x_deg and gaze_y_deg as two primary series. NaN marks blinks and track loss. The target position (xT, yT) is optional auxiliary data. Pupil area (dP) is an integer and out of scope.
- Source: https://figshare.com/articles/dataset/GazeBase_Data_Repository/12912257
- Resources: https://api.figshare.com/v2/articles/12912257, https://ndownloader.figshare.com/files/27039812
- License: CC BY 4.0
- License evidence: https://api.figshare.com/v2/articles/12912257
- License quote: "license": {"value": 1, "name": "CC BY 4.0", "url": "https://creativecommons.org/licenses/by/4.0/"} (figshare article 12912257, GazeBase Data Repository, the only file is GazeBase_v2_0.zip)
- Natural record: One recording CSV: one subject, one session and one task, e.g. Round_1/Subject_1001.zip -> S1/S1_Balura_Game/S_1001_S1_BLG.csv, with columns n,x,y,val,dP,lab,xT,yT. A recording runs about 15-100 s, i.e. 15k-100k rows at 1 kHz.
- Estimated samples: 280
- Estimated primary values: 36,000,000
- Estimated download bytes: 155,000,000
- Estimated primary bytes: 290,000,000
- Decode path: The bulk file is one 6.71 GB zip (zip64) holding 890 nested per-subject zips: Round_1 has 323 entries (322 subjects plus the directory), and Rounds 2-9 hold the rest. I parsed the outer central directory from a 2 MB tail range. Example entry: Round_1/Subject_1001.zip has its local header at offset 19045, 7,293,271 bytes compressed, method 8. download.sh pins (name, offset, compressed size) for a bounded subset, e.g. the first 20 Round_1 subjects. It fetches each nested zip with curl -r through the figshare ndownloader redirect, which answers 206 to range requests. Python stdlib then inflates the outer member (zlib raw deflate, wbits=-15), opens the inner zip with zipfile from bytes, and parses each CSV with csv. x and y are decimal text with 6 decimals, e.g. -11.46039 or -1.955006, and become little-endian float64. f32 cannot round-trip 8 significant digits at magnitudes up to about 30 degrees.
- Novelty kind: new_modality
- Measurement type: eye_gaze_position
- Instrument line: sr_research_eyelink_1000
- Archive collection: figshare.com/GazeBase
- Novelty evidence: `novelty.py --url .../12912257 --terms GazeBase EyeLink gaze`: no matches in recipes, registry, ledger or downstream. `--type eye_gaze_position --archive figshare`: 0 hits for both. The vocabulary has no eye-tracking type; the closest is ui_pointer_trace (mouse traces, f32). Oculomotor signals (fixations, microsaccades, saccade jumps, smooth pursuit) differ from every collected 64-bit family.
- Homogeneity: One instrument (EyeLink 1000, 1 kHz, left eye), one lab protocol, one quantity (gaze angle in dva) and one decimal text format across all recordings. x and y go in separate series. Tasks share the same unit and process, but if the judge wants tighter homogeneity the builder can restrict to fewer task types (e.g. reading plus video plus random saccades) without changing the source. A Round-1-only subset is the simplest pin.
- Risks: (1) Lattice or width honesty. Consecutive x values differ by multiples of about 0.002823 deg, so the gaze is a converted tracker lattice (about 14k levels across the screen) rounded to 6 decimals, not full-mantissa floats. That beats the ISIS case (285 levels) but a judge may still call it decimal-origin f64. The defence is that f64 is the narrowest binary width that round-trips the published decimals. (2) NaN runs during blinks need an explicit missing-value policy, keeping NaN or dropping rows, enforced identically in build.sh and verify.sh. (3) Nested-zip range extraction adds pinned offsets; the figshare S3 redirect URLs are signed, so always go through ndownloader. (4) Human-subject data, but anonymised gaze coordinates only; demographics come in a separate xlsx that should not be fetched.
- Probe evidence: API metadata: one file, GazeBase_v2_0.zip, 6,710,984,652 bytes, CC BY 4.0, published 2021-03-23. A 2 MB range GET on the tail returned EOCD and ZIP64 records; 892 central entries parsed. A 200 KB range from offset 102 decoded the first inner member through two deflate layers, showing header 'n,x,y,val,dP,lab,xT,yT' and rows like '0,-11.46039,-1.955006,0,1142,NaN,NaN,NaN'. Per-subject zips are 7.0-8.5 MB compressed. Round counts: R1 323, R2 137, R3 106, R4 102, R5 79, R6 60, R7 36, R8 32, R9 15 entries.

Proposed by the autocollect scout on 2026-10-09 (transcript `.data/pipeline/logs/scout_64bit/scout.20261009_015508.jsonl`).
