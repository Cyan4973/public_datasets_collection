# GazeBase EyeLink 1000 gaze position (float64)

Left-eye horizontal (`gaze_x_deg_f64`) and vertical (`gaze_y_deg_f64`) gaze
angle in degrees of visual angle. The data were recorded at 1,000 Hz with an
SR Research EyeLink 1000 for GazeBase (Griffith, Lohr, Abdulin and Komogortsev,
Texas State University; *Scientific Data* 8, 184, 2021).

## Source and license

- figshare article 12912257, version 3, DOI 10.6084/m9.figshare.12912257.v3.
  The figshare API declares `"license": {"name": "CC BY 4.0", "url":
  "https://creativecommons.org/licenses/by/4.0/"}`. `download.sh` re-validates
  the license on every run.
- The article has one file, `GazeBase_v2_0.zip` (id 27039812, 6,710,984,652
  bytes, MD5 `cb7eb895fb48f8661decf038ab998c9a`). It is a zip64 archive of
  per-subject zips grouped in `Round_1` … `Round_9`.

## Scope

The recipe covers the first 24 Round 1 subjects in central-directory order
(`Round_1/Subject_1001.zip` … `Subject_1024.zip`). Each subject has 2 sessions
× 7 tasks, giving up to 14 recording CSVs:

| code | task |
|------|------|
| FXS | fixation |
| HSS | horizontal saccades |
| RAN | random oblique saccades |
| TEX | reading |
| VD1, VD2 | free viewing of video |
| BLG | gaze-driven "Balura" game |

A recording runs about 15–100 s, which is 15k–101k rows. Subject 1001 alone
gives 843,669 rows, about 13.5 MB of float64 output for the two axes.

Realized scope: 24 subjects give 336 recordings, of which one (S_1018_S1_HSS,
52.2% NaN) is excluded by the rule below. That leaves 335 recordings: BLG, FXS,
RAN, TEX, VD1 and VD2 have 48 each, and HSS has 47.

| series | samples | bytes | values |
|--------|---------|-------|--------|
| `gaze_x_deg_f64` | 335 | 167,782,088 | 20,972,761 |
| `gaze_y_deg_f64` | 335 | 167,782,088 | 20,972,761 |

Total primary output is 335,564,176 bytes, from 186,992,147 bytes of
downloaded inner zips. The median sample is 60,087 values. Overall NaN fraction
is 3.69%, with a per-sample maximum of 40.5%.

## Download

`scripts/pinned_members.tsv` pins each member's name, local-header offset,
range length, compressed and uncompressed size, and CRC32. These values come
from the outer zip64 central directory.

`download.sh` does the following:

1. Fetches and validates the article JSON.
2. Fetches each member's exact byte range through
   `https://ndownloader.figshare.com/files/27039812`. That URL redirects to a
   short-lived signed S3 URL, so the redirect target is never pinned.
3. Checks each response: HTTP 206, exact `Content-Range`, local header, and a
   raw-DEFLATE end exactly at the member boundary.
4. Checks the inflated inner zip: CRC32, `zipfile.testzip`, the CSV member
   names, and the 8-column header.
5. Stores only the inflated inner zip.

The demographics workbook `GazeBaseDemoInfo.xlsx` is never requested.

## Conversion

- Columns are located by header name, because the order differs by task (e.g.
  `n,x,y,val,dP,lab,xT,yT` vs `n,x,y,val,xT,yT,dP,lab`).
- Each `x` and `y` token becomes `float()` and must round-trip its source
  decimal exactly (at most 6 fractional digits).
- Values are packed in source row order as little-endian float64, one file per
  recording and axis: `samples/<id>/<series>/S_<subject>_S<session>_<TASK>.bin`.
- **NaN policy:** the literal `NaN` marks blinks and track loss (exactly the
  rows with `val = 4`). It is kept in place as the canonical quiet NaN
  `0x7FF8000000000000`, so the 1 kHz alignment is preserved.
- **Exclusion rule:** a recording is dropped for both axes only if either axis
  has fewer than 1,000 finite values or more than 50% NaN.
- Per-sample NaN counts and fractions are recorded in the index and in
  `filtered/<id>/ingest_stats.json`.
- Not emitted: `n`, `val`, `dP` (integer pupil area), `lab` (event labels),
  and `xT`/`yT` (target position, NaN outside the target-driven tasks).

## Verification

`verify.sh` re-parses every CSV independently, using `csv.DictReader` and a
normalized-Decimal round-trip check. It then:

- re-derives every sample and compares it byte-for-byte;
- checks the index fields: size, value count, NaN count, finite min/max and
  SHA-256;
- applies the same exclusion rule as the build;
- rejects constant samples and samples with fewer than 10 distinct values;
- checks the manifest's `sample_count` and `total_size_bytes`.

## Caveats

- **Decimal origin.** Values are converted from the tracker's internal lattice
  and rounded to 6 decimals. The steps are 0.1 px of the 1680×1050 px
  (474×297 mm) display viewed at 550 mm. That is about 0.0029 deg at screen
  centre, smaller with eccentricity.
- **Float32 coverage.** Measured over all 40,396,050 emitted finite values:
  - 641,515 values (about 1.6%) cannot be reproduced from float32, i.e.
    `round(float32(v), 6) != v`.
  - All of them have |value| ≥ 16 deg, where the float32 ulp exceeds 1e-6.
    3.3% of values lie in that range.
  - Only 12,391 values (about 0.03%) are exactly representable in float32.

  float64 is the narrowest IEEE width that reproduces every published
  decimal.
- **Personal data.** These are de-identified, subject-coded eye-movement
  recordings from college-aged volunteers. They were collected under a Texas
  State University IRB protocol: subjects gave informed consent and
  acknowledged dissemination in de-identified form (Griffith et al. 2021,
  *Sci Data* 8:184).
  - Eye-movement signals have biometric character even without names or
    demographics; GazeBase was designed for eye-movement biometrics. The
    manifest therefore sets `contains_personal_data = true`.
  - `GazeBaseDemoInfo.xlsx` is never requested.
  - Use only under CC BY 4.0. Do not attempt participant identification,
    linkage, health inference, or biometric profiling.
- **Task mix.** The seven tasks share one instrument, unit, lattice and
  protocol, but their gaze dynamics differ (fixation jitter, saccade steps,
  reading sweeps, free viewing). If tighter homogeneity is needed, the next
  step is to restrict tasks within this same source.
