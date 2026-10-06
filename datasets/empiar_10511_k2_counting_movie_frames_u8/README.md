# EMPIAR-10511 Cryo-EM Gatan K2 Electron-Counting Movie Frames UInt8

This recipe collects 40 raw dose-fractionated cryo-EM movie frames, each a
3838x3710 raster of per-pixel electron counts in native 8-bit form. They come
from EMPIAR-10511 ("mouse cGAS with nucleosomes from 293T"; Zhao, Xu et al.,
Nature 2020, DOI 10.6019/EMPIAR-10511).

The entry deposits 2979 unaligned, unnormalized movies recorded on a Gatan K2
Summit in counting mode. EMDB EMD-22047 gives the acquisition setup: FEI
Titan Krios, 300 kV, 48 e/A^2 total exposure, defocus 0.8-2.0 um. Each movie
holds 40 frames at 1.07 A per pixel.

## Licence

The EMPIAR FAQ (<https://www.ebi.ac.uk/empiar/faq>) states: "All data in EMPIAR
is freely and publicly available to the global community under the CC0
license". `download.sh` fetches the FAQ and fails if that sentence disappears.
The accepted `empiar_13192_sbfsem_vessel_slices_u8`, `empiar_10994_*` and
`empiar_10318_*` recipes rest on the same licence statement.

## What is collected

- **Which movies.** 40 movies sit at the bin centres of 40 equal bins over the
  2979 name-sorted movies (listing indices `floor((2s+1)*2979/80)`, so 37, 111,
  186, ..., 2941). They span both acquisition days (2020-03-04 15:49 to
  2020-03-05 12:25) and all four EPU acquisition templates. The 40 movies are
  pinned in `scripts/k2_movies.tsv`.
- **Which frame.** Every movie contributes the same section, z = 20 (0-based;
  the 21st of 40 frames, mid-exposure). Every sample therefore sits at the same
  dose position and the same accumulated dose. One frame per movie keeps
  samples from 40 independent exposures instead of 40 near-identical frames of
  one exposure.
- **Sample layout.** One sample per frame: 3710 rows x 3838 columns of uint8,
  row-major as stored. That is 14,238,980 values per sample and 569,559,200
  bytes in total.
- **Download.** Per movie, two HTTP range requests: the 1024-byte header and the
  14,238,980-byte frame. 569,600,160 bytes in total, plus the EMPIAR entry JSON
  and the FAQ page. Whole movies (569.6 MB each, 1.70e12 bytes for the entry)
  are never fetched.

## Why this material

Counting-mode direct-detector frames are a distinct compression regime. Each
pixel reports how many individual electrons were detected during one short
dose fraction:

- the realized frame means are 0.825-0.990 e/pixel/frame (median 0.875), each
  within 0.2 % of its movie's header DMEAN;
- 37-44 % of pixels are 0. Pooled over all 40 frames the value frequencies are:

  | value | 0 | 1 | 2 | 3 | 4 | 5 or more |
  |---|---|---|---|---|---|---|
  | share of pixels | 41.8 % | 36.3 % | 15.9 % | 4.7 % | 1.0 % | 0.2 % |

  Only 7.4e-7 of all values exceed 10;
- per-frame histogram entropy is 1.73-1.88 bits/value (median 1.77), with
  16-24 distinct values per frame;
- zlib level 1 gets each frame to 0.327-0.342 of its raw size;
- a handful of isolated pixels per frame (3-14 values at 16 or more) hold
  larger values, giving frame maxima of 31-80. These are hot or bright pixels, and some recur at
  fixed coordinates: in slot 0, pixel (row 1770, column 721) reads 44 in frame 0
  and 43 in frame 20.

This low dynamic range is native to the instrument. The detector really
outputs small integers per frame, and 8 bits is the narrowest standard width
and the format GMS wrote. The frames are not rescaled, aligned, summed or
gain-normalized.

Nearest existing families:

- `zenodo_tem_tilt_series_i16`: dense integrated TEM projections.
- `empiar_10318_microed_diffraction_frames_u16`: integrating-camera
  diffraction patterns.
- `empiar_13192_sbfsem_vessel_slices_u8` and
  `empiar_10994_sbfsem_bsed_slices_u16`: scanned backscatter images.

None of these is a sparse electron-count frame. `tools/autocollect/novelty.py`
finds no counting-mode or cryo-EM movie material locally or downstream.

## Decode

Each movie is an MRC file written by Gatan DigitalMicrograph (label
`Digital Micrograph(TM), GMS v 3.23`). Its header holds:

- NX/NY/NZ = 3838/3710/40 and MODE 0;
- NSYMBT = 0, so there is no extended header;
- MAPC/MAPR/MAPS = 1/2/3, so x is the fastest axis;
- a little-endian machine stamp;
- DMIN/DMAX/DMEAN statistics. GMS computes these from the first frame only,
  not the whole stack. In slot 0, DMAX 44 equals the maximum of frame 0 while
  frame 20 reaches 64, and DMEAN 0.8641 matches frame 0's mean of 0.8627. The
  recipe therefore compares each frame with DMEAN, since the dose rate is
  constant, but never with DMIN/DMAX. The first download attempt failed on
  exactly that wrong assumption.

Section k therefore starts at byte `1024 + k*14,238,980`. Frame 20 occupies
bytes 284,780,624-299,019,603, and the file size is exactly 569,560,224. The
parser checks every header field listed in `manifest.toml`, then the frame
bytes are copied unchanged. The code is pure standard-library Python.

**Signedness.** MRC2014 defines mode 0 as signed int8; IMOD historically reads
it as unsigned. EMPIAR declares the imageset `UNSIGNED BYTE`. All values here
are non-negative counts. Build and verify require every emitted frame's maximum
to be at most 127, so both readings give identical numbers and the samples are
labelled uint8. Download only warns on a larger value, because a large count is
still a valid uint8 reading and the transfer should not be thrown away.

**Excluded file.** `gain-reference.mrc` in the same directory is a
3838x3710x1 float32 (mode 2) gain-correction map. It is not detector counts
and is excluded. Movie names must match `FoilHole_*_Data_*.mrc` and every pin
has the exact movie size.

## Pins and validation

`discover.sh` is metadata-only (about 3.6 MB). It resolved the pins as follows:

1. Parse the `data/` autoindex and require exactly 2979 movies listed at 543M
   plus the 54M gain reference.
2. Select the bin-centre movies.
3. For each selected movie, record the HEAD Content-Length, the SHA-256 of the
   1024-byte header and the SHA-256 of the first 65,536 bytes of frame 20.

`download.sh` handles the transfer and validation:

- **Range requests.** Each range resumes from the bytes already on disk and is
  stall-bounded (`--speed-limit 1024 --speed-time 120`, never `--max-time`). A
  response chunk is kept only if it is a 206 with Content-Range
  `bytes FROM-END/569560224`. `--max-filesize` stops a server that ignores
  `Range` from streaming a whole movie.
- **Header checks.** Each header must match its pinned SHA-256 and pass the
  structural checks.
- **Frame checks.** Each frame must have the exact length, match the prefix pin
  and pass the degeneracy checks:
  - maximum at most 127 (a warning here; fatal in build and verify);
  - at least 8 distinct values;
  - mean 0.5-1.5 e/pixel and within 25 % of the header DMEAN;
  - modal value covering at most 75 % of pixels;
  - at most 37 constant rows or columns;
  - unique payload.
- **Whole-frame pins.** Whole-frame SHA-256 pins were recorded from the
  2026-10-06 autocollect download (all 40 frames validated on the first
  attempt) with
  `python3 scripts/k2_movie_frames.py pin-frames --download-dir ...`. From then
  on, download, build and verify all enforce them, and build refuses unpinned
  frames.

`verify.sh` re-derives every frame from the downloaded ranges and checks the
following:

- each sample is byte-identical to its source frame;
- per-frame statistics and index rows match a fresh recomputation;
- the sample directory matches the index exactly;
- the manifest totals match the realized output;
- the pinned output digest
  (`1f736f4887d93b62c74579e725e7b50a3c9c3f30ab03a433d73d83787e353926`) still
  holds.

## Caveats

- **Uncorrected detector output.** The frames are raw, unnormalized counts.
  Fixed-pattern gain variation and any detector defects are part of the
  material, as acquired. Frame-0 maxima of 19-79 (header DMAX) and the
  frame-20 maximum of 64 in slot 0 far exceed what Poisson counting at this
  dose produces (the bulk of each frame stays below about 10). They come from
  a few isolated hot or bright pixels, some at recurring coordinates. Their
  count is recorded per sample as `hot_values`.
- **Domain.** This is structural-biology material. It is the fourth
  EMPIAR-sourced family in the corpus and the second at 8 bits, but a
  different modality from the SBF-SEM families.
- **Sample size.** Samples are large (14.2 MB each). They are kept whole as
  natural detector frames and are not tiled.
