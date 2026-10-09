# DFL Bundesliga position tracking float32 development

## Outcome

Accepted `figshare_dfl_bundesliga_position_tracking_f32`: official DFL optical tracking of every player and match official, 25 frames per second, across all seven matches in the Bassek et al. (2025) integrated elite-soccer dataset.

This is the first sports player-tracking family in the corpus at any width. Local and downstream trajectory families are vessel AIS, ADS-B, GNSS, bike-trip and INS tracks, plus laboratory mocap marker trajectories. None of them is optical tracking of people moving on a playing field. Measured breadth is OK (nearest distance 0.078–0.087).

## Source and rights

- Source: figshare article 28196177 version 1, *An integrated dataset of spatiotemporal and event data in elite soccer*, DOI 10.6084/m9.figshare.28196177.v1. It supplements Scientific Data, doi:10.1038/s41597-025-04505-y.
- Files: the seven `DFL_04_03_positions_raw_observed_<competition>_<match>.xml` documents.
  - 2,622,603,272 bytes in total, 348,945,715–418,524,833 bytes each.
  - Pinned by figshare file id, size and MD5 in `sources.tsv`.
- License: CC BY 4.0. The live figshare API record declares `{'value': 52, 'name': 'CC BY'}`. The paper states the release is "under a CC-BY 4.0 license with the authorization from the DFL" and that consent to publish is given when players register.
- What is not fetched: the matchinformation files (which map ids to names) and the event files. Samples carry only opaque DFL-MAT and DFL-OBJ ids.

## Shape and conversion

Each natural record is one `<FrameSet>`: one player or official, for one half, of one match.

- Values: every 40 ms `<Frame>` carries two-decimal attributes `X` and `Y` (metres, centre-spot origin) and `S` (speed in km/h, which the paper confirms).
- Encoding: each value is parsed once with `float()` and stored as little-endian float32.
- Series: three primary series, `person_x_f32`, `person_y_f32` and `person_speed_f32`, one sample per FrameSet.
- Excluded:
  - the 14 BALL FrameSets, which add Z, BallStatus and BallPossession;
  - `D`, distance covered per frame in cm, which duplicates S in other units;
  - `A`, acceleration;
  - the bookkeeping fields `N`, `T` and `M`.
- Fatal conditions in the build: missing or malformed values, non-increasing frame numbers, duplicate FrameSets, unknown TeamIds.

S is the provider's own per-frame speed channel. It tracks a smoothed finite difference of X/Y very closely (r ≈ 0.9995). It is kept because it is a published, machine-facing operational channel, with the same precedent as OpenSky velocity stored next to positions. It is not needed to clear any floor.

## Accepted output

| | |
|---|---|
| Matches | 7: 2 from the 1. Bundesliga, 5 from the 2. Bundesliga, 2022/23 season |
| FrameSets per series | 380: 368 player, 12 referee (referees appear only in the two 1. Bundesliga files) |
| Primary samples | 1,140 (3 × 380) |
| Primary values | 68,210,454 (22,736,818 per series) |
| Primary bytes | 272,841,816 (90,947,272 per series) |
| Sample length | min 2,352, median 69,131, max 78,456 frames; no frame gaps |

Value ranges, from the stored float32 values:
- X: −55.50 to 55.50 m. The ±55.50 limit is the tracking area 3 m past the goal line. It is reached in 10,956 frames across 35 samples.
- Y: −38.60 to 38.08 m.
- S: 0.00 to 36.30 km/h.

Other properties:
- Highest share of a single value in any sample: 7.48%, an assistant referee's Y on the touchline.
- Index SHA-256: `952ad43996a212e4e70bff79924374c36b3527d23cca659ad20a89494305ab4f`, identical across three independent build and verify runs.

## Judge checks

- **Gate:** `gate.py` PASS, no warnings.
- **Verify:** I re-ran `verify.sh`, which exited 0. It re-derives all 1,140 samples byte-for-byte with an independent `xml.etree.iterparse` + `struct '<f'` path.
- **Determinism:** the index hash matched the builder's and the driver's runs.
- **Bytes:**
  - Read 8 FrameSets with `struct`: random players, the shortest substitute and a referee. Checked the 0.01 lattice, ranges, distinct-value counts, constant runs and deltas.
  - Scanned all samples for duplicate hashes (none), mode share (≤7.5%), frame jumps (>3 m in about 0.001% of frames) and X clipping.
  - Spot check: the first 2,000 frames of one raw XML FrameSet matched the X, Y and S sample bytes exactly.
  - Every S sample starts at 0.00, because the provider has no previous frame.
- **Speed semantics:** S against a 10-frame centred-difference speed gives r 0.967–0.9999 with a mean error of about 0.07 km/h. This confirms km/h and that S is provider-derived. The paper's field table confirms the units of X, Y (m), D (cm), S (km/h) and A (m/s²).
- **Rights:** fetched the figshare API record live (CC BY, exact files and MD5s) and read the Data Records and ethics text in the paper via Europe PMC (PMC11787359). No credentials in any script; build and verify make no network calls.
- **Novelty:** `novelty.py` term, URL, type, instrument and archive queries found no soccer or tracking family locally, downstream or in the registry. The only host overlap is the multi-tenant ndownloader.figshare.com, for which the user approved the breadth override. zlsim measured OK: X 0.0874, Y 0.0797, S 0.0778.
