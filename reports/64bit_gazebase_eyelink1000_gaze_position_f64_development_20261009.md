# GazeBase EyeLink 1000 gaze position float64 development

## Outcome

Accepted `gazebase_eyelink1000_gaze_position_f64` from the official GazeBase figshare deposit (article 12912257, version 3), after one text-only repair cycle.

This is the corpus's first eye-tracking family at any width. Each sample is left-eye gaze angle in degrees of visual angle from one recording, sampled at 1 kHz by an SR Research EyeLink 1000 (pupil–corneal-reflection video oculography). Each recording covers one subject, one session and one task. Horizontal (`gaze_x_deg_f64`) and vertical (`gaze_y_deg_f64`) gaze are separate primary series.

The repair cycle changed only metadata:
- `contains_personal_data` is now `true`, with de-identification, IRB and biometric-use notes following the Fukuchi precedent.
- The overstated float32 round-trip claim ("about a third") is corrected to the measured 1.588%.

## Source and rights

- Source: figshare article 12912257 v3, DOI 10.6084/m9.figshare.12912257.v3, published 2021-03-23 by Griffith, Lohr and Komogortsev (Texas State University).
- Bulk file: `GazeBase_v2_0.zip`, id 27039812, 6,710,984,652 bytes, MD5 `cb7eb895fb48f8661decf038ab998c9a`. It is a zip64 archive of per-subject zips.
- License: CC BY 4.0. The figshare API declares it for the article, and the data descriptor (Griffith et al., *Sci Data* 8:184, 2021) states "GazeBase is distributed under a Creative Commons Attribution 4.0 International (CC BY 4.0) license."
- Human subjects: the descriptor states that participants gave informed consent under a Texas State University IRB protocol and "acknowledged that the resulting data may be disseminated in a de-identified form", and that "all data have been de-identified."
  - The manifest marks the data as personal (biometric character) but not sensitive.
  - It prohibits re-identification, linkage, health inference and biometric profiling.
  - The demographics workbook `GazeBaseDemoInfo.xlsx` is never requested.

## Shape and conversion

- **Subset.** `download.sh` fetches 24 pinned outer-zip members (`Round_1/Subject_1001.zip` … `Subject_1024.zip`) through exact HTTP range requests on the ndownloader URL.
  - Each response must be HTTP 206 with an exact Content-Range.
  - The local header must match the pin, and the raw DEFLATE stream must end exactly at the member boundary.
  - The inflated inner zip must match the pinned size and CRC32, pass `testzip`, and contain only the expected CSV names and the 8-column header.
- **Natural record.** One recording CSV (subject × session × task), with columns `n,x,y,val,dP,lab,xT,yT` in task-dependent order. Recordings run 15–126 s, i.e. 15k–126k rows.
- **Conversion.** `x` and `y` are located by header name, parsed with `float()` (checked for decimal round-trip) and packed as little-endian float64 in source row order. There is one file per recording and axis, with no concatenation.
- **Missing values.** The source writes `NaN` exactly on rows with `val = 4` (blink or track loss). It is kept in place as canonical quiet NaN `0x7FF8000000000000`, preserving 1 kHz alignment.
- **Exclusion.** A recording is dropped (both axes) if either axis has fewer than 1,000 finite values or more than 50% NaN. Only `S_1018_S1_HSS` is dropped (52.2% NaN).
- **Width.** Values are published decimals with 6 fractional digits on a 0.1-px lattice: about 0.0029° at screen centre for the 1680×1050 px, 474×297 mm display viewed at 550 mm.
  - Over all 40,396,050 finite values, 641,515 (1.588%) cannot be reproduced from float32. All of them have |v| ≥ 16°, where the float32 ulp exceeds 1e-6.
  - Only 12,391 (0.0307%) are exactly representable in float32.
  - float64 is therefore the narrowest lossless IEEE width.
- **Not emitted:** `n`, `val`, `dP` (integer pupil area), `lab`, `xT`, `yT`.

## Accepted output

- Subjects: 24 (Round 1, 1001–1024)
- Recordings decoded: 336, of which 1 excluded and 335 emitted (BLG, FXS, RAN, TEX, VD1 and VD2 have 48 each; HSS has 47)
- Primary samples: 670 (335 per series)
- Primary values: 41,945,522 (20,972,761 per series)
- Primary bytes: 335,564,176 (167,782,088 per series)
- Minimum / median / maximum sample: 15,070 / 60,087 / 125,697 values
- NaN fraction: 3.694% overall; per-sample maximum 40.5%
- Downloaded inner-zip bytes: 186,997,528, from 185,124,819 bytes of range-fetched outer members
- Index `samples.jsonl` SHA-256: `ffe72fdeb103b4c4681bab1a1009a2953cecbd2fa4d636a0985c463e21ac8dc5`
- Measured breadth (zlsim): OK. x is nearest `appliances_energy_uci:appl_t6` at 0.080, and y is nearest `appliances_energy_uci:appl_t_out` at 0.100.

## Judge checks

- **Gate.** `python3 tools/autocollect/gate.py staging/<id>` passes with no warnings.
- **Verify.** I reran `bash staging/<id>/verify.sh`: exit 0 in 2m25s, `verify_ok samples=670 excluded_recordings=1 max_source_decimals=6`. build.sh reads only local inner zips.
- **Rights.**
  - I fetched the live figshare API: CC BY 4.0, and the file id, size and MD5 match the pins.
  - I read the data descriptor full text (Europe PMC PMC8285447) for the license, de-identification and IRB/consent statements, and confirmed the display geometry (1680×1050 px, 474×297 mm, 550 mm).
  - No credentials appear in any script.
- **Bytes.**
  - I read samples with stdlib `struct`/`array` across all 7 tasks, both axes and 3 subjects each. The ranges are physically plausible: about ±21° for video and game, ±15° for horizontal saccades, ±8–10° for reading, and near 0 for fixation.
  - Minimum steps are 0.0024–0.0029°.
  - NaN is canonical and aligned between x and y in all 335 recordings.
  - There are no duplicate sample hashes.
  - Independent `zipfile` + `csv` decodes of three recordings (1006 S1 TEX, 1014 S2 VD2, 1020 S1 RAN) match the emitted bytes exactly, with NaN on exactly the `val = 4` rows.
  - The excluded 1018 S1 HSS recording has 52.2% `val = 4` rows.
- **Repair claims.** I recomputed the float32 statistics over every finite value and got the builder's exact counts (641,515 / 12,391 / 3.316% with |v| ≥ 16°). The `[safety]` block and README "Personal data" caveat match the requested wording and the precedent of the 9 accepted de-identified human-signal recipes.
- **Novelty.**
  - `novelty.py --url` (API and ndownloader) with GazeBase/EyeLink/gaze/saccade/oculomotor/eyetracking terms finds no family other than this candidate; the remaining hits share only the figshare host.
  - `--type/--instrument/--archive` returns 0/0/0.
  - The vocabulary has no eye-tracking type.
  - A downstream filename search found no gaze families.
- **Homogeneity.** One instrument, lab geometry, unit, lattice and text format. Task and subject differences change dynamics and noise level, not scale or lattice.
