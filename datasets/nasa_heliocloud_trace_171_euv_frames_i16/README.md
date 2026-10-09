# TRACE 171 A full-frame EUV images, 1998 near-lossless frame programs (int16)

Whole 1024 x 1024 int16 images of the solar corona taken by NASA's TRACE telescope
in the 171 A (Fe IX/X) passband, from the SDAC TRACE holdings in the NASA GSFC
HelioCloud bucket (`gov-nasa-hdrl-data1/sdac/trace/`). One sample is one FITS
file: one exposure, copied unchanged as little-endian int16.

## What the archived values are

The scout card described these as level-0 DN. They are not. Every SDAC file
header records `trace_prep` processing:
- `tr_dark_sub 2.10`: dark pedestal and current subtracted;
- `tr_flat_sub 1.60`: divided by a corrected flat field;
- `trace_wave2point`: pointing header only.

The results were rounded back to BITPIX 16, so values go negative near zero
(down to -90 in the kept set). The header is 5,760 bytes (two FITS blocks), not
8,640 as the card stated. The `a0`/`a1`/`a2` key suffix is the header
`SOU_AREA` source-area index; `a2` files are 768 x 768 extracts. Only `a0`
(SOU_AREA = 0) full frames are used.

## Regime

### Onboard JPEG mode: the frame program, then a ringing test

The TRACE Analysis Guide says TRACE compressed every image with a modified
12-bit JPEG: "a nearly lossless mode that preserves 12-bit data with a maximum
error of 1 count and a wide range of lossy options". No header keyword states
the mode. The frame program (`FRM_NAM`) does predict it, and both the header
regime and the data regime use it.

**Allowlist.** These programs are admitted:
- programs whose name contains `lossless`, e.g. `com.losslessdefaecfull_171`;
- programs whose name ends in `Q0`, e.g. `cjs.stdfull171Q0`;
- `cjs.caldc171`, the disk-centre calibration and synoptic program.

`ras.jpeg171.aecm4` is conditional: it is admitted only when the ringing test
can be run on at least 20 spike cells (see below). Every other program is
excluded. That includes `cjs.stdaecfull171`, `cjs.stdfull171`,
`ras.aecfb171*`, `cck.FeX.*` and the aecoffset programs.

**Ringing test.** Lossy JPEG rings around particle spikes, leaving undershoot
in the surrounding 8 x 8 cell. The test works on spike cells: aligned 8 x 8
cells (rows and columns 8..1015) whose median is below 60 DN and whose maximum
is above 400 DN.
- D = median over spike cells of (cell minimum - cell median).
- When a frame has at least 5 spike cells, D must be greater than -15 DN.
- A frame with fewer spike cells can be kept only if its program is
  allowlisted and no pixel is below -15 DN.

On the first-cycle pool, D separated two groups:
- near-lossless programs: -5 to -11 DN;
- the now-excluded lossy programs: -23 to -82 DN.

The kept frames have D from -11 to -5. The earlier cell-edge blockiness ratio
(mean |neighbour difference| across cell boundaries over the mean inside
cells, 0.80-1.06) is kept only as a secondary filter. It cannot see
ringing-type lossy frames, which pass it. In the previous cycle it let 68 lossy
frames through, so it is not relied on.

### Calibration gain drift: no empty near-zero bin

Near zero the histogram of a frame is `round(g * k)`, where g is a
time-dependent factor applied in the flat field. Near-zero pixels have small k,
so the per-pixel flat variation does not blur the pattern there. When g > 1
some integer bins are skipped. **g is not exactly 1 anywhere in the window.**
The skipped bin moves toward zero as g grows:
- k ~ 42-45 at the end of April (g ~ 1.02);
- |k| ~ 33 in May, ~14 in June and ~8 in August (the judge's measurements);
- k = 6 from late September (g ~ 1.09).

Later years drift much further: about 1.25 in mid-1999, about 1.45-1.5 in
2000 and later, up to about 1.9 in 2003. At those gains periodic empty bins
appear inside the noise peak itself. That is why the window ends on
1998-10-31.

The rule is: no empty near-zero bin. For k = -60..1500, a bin is tested when
both neighbours hold at least 300 pixels. A tested bin fails when it holds
fewer than 0.5 x the smaller neighbour. A frame needs at least 8 tested bins
and no failures.
- The index records `lattice_tested_bins`, `lattice_worst_k` and
  `lattice_worst_ratio`, the most depleted tested bin relative to its smaller
  neighbour.
- The kept minimum ratio is 0.516 (1998-08-27 09:46, k = 8).
- Kept September and October frames show a partial dip at k = 6, with ratios
  of 0.60-0.79.

So the kept set is "no empty near-zero bin", not "unit gain". A gain of a few
per cent still thins individual bins.

### Other filters

The pool also excludes:
- non-canonical processing histories, which are common: frames flat-fielded
  or dark-subtracted twice, frames with missing pixels filled with the image
  average, and frames with a bad-pixel map applied;
- other wavelengths;
- binned or summed frames, and amplifier other than A;
- partial frames (PERCENTD < 100);
- exposures under 1 s, and frames with IMG_MAX < 300;
- degenerate frames: a dominant value or zeros above 15%, fewer than 256
  distinct values, or constant rows or columns.

## Realized output

- Discovery: 8,234 headers read; 222 passed the header regime, including the
  program allowlist. 95 frames on 80 days were pinned (at least 3 h apart, at
  most 2 per day): 200,001,600 bytes downloaded.
- 72 kept frames on 65 days, 150,994,944 bytes of int16 samples.
- Kept frames per month: April 7, May 13, June 10, July 14, August 17,
  September 8, October 3.
- Rejected by first reason:
  - 9 empty near-zero bin: 1998-04-26..28 at k = 42-45, and k = 6 from
    1998-09-28 on;
  - 12 degenerate: 11 with fewer than 256 distinct values, mostly short
    disk-centre synoptic exposures, and 1 with 16% zeros;
  - 2 ringing-untestable: a `cjs.caldc171` frame with no spike cells and one
    pixel below -15, and the only `ras.jpeg171.aecm4` frame, which had 18
    spike cells.
- By program:
  - `cjs.caldc171` 48: CJS.scene.caldiskcenter 29, CJS.scene.CDSsynoptic 19;
  - `com.losslessdefaecfull_171` 9: STD.focus_euv;
  - `cjs.stdfull171Q0` 8: STD.fdm.bulletproof;
  - `com.losslesslastaecfull_171` 6: TDT.uv_subpixel 5, STD.flats_171 1;
  - `cjs.stdaecfull171Q0` 1: CJS.tracking.
- Exposures 2.9-78 s; values -90..5,110; 263-2,875 distinct values per frame;
  dominant value at most 7.8%.

**Caveat.** Two thirds of the kept frames are disk-centre calibration or
synoptic pointings, so scene variety is narrower than "TRACE 171 A" suggests.
The scope is six months of 1998 near solar minimum, not a solar cycle.

## Pipeline

- `discover.sh` / `scripts/discover.py` (authoring only):
  - lists every day prefix `sdac/trace/1998/MM/DD/trac_171____a0_` in the
    window;
  - range-reads the headers of up to 32 evenly spaced frames per day, plus
    every 00 UT frame (where the isolated `cjs.caldc171` synoptic frames sit);
  - applies the header regime, then the spacing policy;
  - writes `sources.tsv`.
- `download.sh`: curl, resumable.
  - Enforces size, MD5 = ETag, the header regime, pinned header facts and zero
    padding.
  - Records SHA-256s in `download_plan.tsv`.
  - Removes unpinned FITS files from its own directory.
  - Fetches, best effort, the TRACE data policy page and the NASA SMD policy
    page as rights evidence.
- `build.sh`: runs `scripts/selftest.py` on synthetic frames, which exercises
  both the build and the verify code paths: clean, ringing, gain-1.5, blocky,
  flat, program classes and header rejections. Then `scripts/build.py` measures
  every pool frame, writes `filtered/<id>/pool_metrics.tsv` and
  `ingest_stats.json`, and keeps the frames that pass the data regime.
- `verify.sh`: `scripts/verify.py` independently re-implements the header walk,
  decode, program classes and metrics. It re-derives the kept set,
  byte-compares every sample and checks the index, manifest totals and scope
  (at least 20 samples over at least 5 months).

## Rights

TRACE data policy page: "All TRACE data will be equally available to everyone
on the World Wide Web." NASA SMD open scientific data policy, the same basis as
the accepted `nasa_heliocloud_iris_l1_fuv_frames_i16` from the same bucket.
Neither page is a named license. Cite Handy et al. 1999, Solar Physics 187, 229.
