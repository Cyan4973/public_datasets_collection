# EMPIAR-10318 200 kV MicroED diffraction frames (uint16)

Raw electron-diffraction detector frames from the EMPIAR entry
[EMPIAR-10318](https://www.ebi.ac.uk/empiar/EMPIAR-10318/), *200kV MicroED
structure of FUS (37-42) SYSGYS solved from merged datasets at 0.65 A*
(Zhou, Luo, Luo, Li, Liu, Li; DOI 10.6019/EMPIAR-10318; Anal. Chem. 2019,
DOI 10.1021/acs.analchem.9b01162; EMD-0696, PDB 6KJ1).

Eight peptide nanocrystals were each rotated continuously in an FEI Tecnai
F20 at 200 kV (wavelength 0.025071 A). Every frame integrates a 1 degree
wedge over 5.72 s on a 4096x4096 camera. The depositors converted the frames
to SMV so that X-ray software would read them: the header claims a 51 um
pixel and an equivalent 3064 mm camera distance (an ADSC Q210 imitation), but
the pixel values are not rescaled. Each series is one ZIP archive of
`D520mm_NNNN.img` members plus a `.cec` beam-centre sidecar.

## What is collected

| | |
|---|---|
| Series | `microed_200kv_diffraction_frame_u16` (primary, `native_numeric`) |
| Samples | 24 frames, 3 per crystal series x 8 series |
| Sample | 4096 x 4096 little-endian uint16 (33,554,432 bytes; 16,777,216 values) |
| Total | 805,306,368 bytes |
| Download | 342,054,163 bytes of exact ZIP byte ranges (plus about 51 KB of metadata pages), out of 10.17 GB of archives |
| License | CC0 1.0 (EMPIAR FAQ: "All data in EMPIAR is freely and publicly available to the global community under the CC0 license") |

Selection: in each series of `n` frames (name order) the recipe keeps the
frames at positions `floor(n*(2k+1)/6)`, `k = 0, 1, 2`. These are the 1/6,
1/2 and 5/6 points of the sweep, which avoids the first and last wedges and
spans rotation angles from -50 to +35 degrees overall. The whole entry has
713 frames of 33.5 MB each, so at most 29 fit under the 1 GB cap. Taking
three per crystal keeps all eight crystals equally represented.

Each frame is one natural record: one SMV file, i.e. one rotation wedge.
Frames are never tiled, cropped or concatenated.

## Pipeline

- `discover.sh` documents how the pins were resolved, using only small
  requests: the directory listing, a HEAD plus a 64 KiB tail range per
  archive, and the first 4 KiB of each selected member. It regenerates
  `scripts/archives.tsv` and `scripts/frames.tsv` and diffs them against the
  committed copies.
- `download.sh` fetches the EMPIAR entry JSON, the FAQ (licence sentence
  check) and the directory listing (exactly the 8 archives). Per archive it
  takes the central directory plus end records (SHA-256 pinned). Per
  selected frame it takes the exact range covering the local header, name
  and DEFLATE data. Range chunks must come back as `206` with the exact
  `Content-Range`. Partial ranges resume from the bytes already on disk,
  under curl stall limits (`--speed-limit 1024 --speed-time 120`). Each
  member is inflated, CRC-checked and SMV-validated before it is moved into
  place.
- `build.sh` inflates each member, validates it again, computes per-frame
  statistics and the degeneracy floor, and writes the pixel block (bytes
  512..) as one raw sample. It also writes
  `index/<id>/samples.jsonl` and `filtered/<id>/ingest_stats.json`.
- `verify.sh` re-inflates every member with a separate one-shot decoder and
  a regex header check. It byte-compares the samples, recomputes the
  statistics and index rows, requires that the sample directory match the
  index exactly, and checks the manifest's `sample_count` and
  `total_size_bytes`.

All logic is in `scripts/microed_smv.py` (pure standard library).

## ZIP details worth knowing

- Local headers have extra length 0. The central directory has a 32-byte
  NTFS timestamp extra (header id 0x000A) that is not repeated locally. The
  recipe reads the local header's own lengths and requires the data to end
  exactly at the pinned range end.
- Seven of the eight archives (all except `20180316_144-204.zip`) end with a
  ZIP64 end-of-central-directory record and locator, even though every
  offset and size fits in 32 bits. The parser validates those records but
  needs no ZIP64 sizes.
- No member uses a data descriptor (general-purpose flags are 0).

## Value range and the signed/unsigned question

EMPIAR's imageset metadata says `SIGNED 16 BIT INTEGER`. Every SMV header
says `TYPE=unsigned_short`, so the recipe follows the header. Realized over
the 24 frames (2026-10-06 build):

- global range 0..32,747. Every frame stays at or below 32767
  (`all_frames_max_le_32767 = true`, 0 pixels above 32767), so the sign
  question is moot and the data use 15 bits of magnitude. Per-frame maxima
  run from 10,141 to 32,747 and the top values are singletons, with no
  pile-up at a saturation ceiling.
- per-frame median 7 to 19, 99th percentile 114 to 331, 99.99th
  percentile 391 to 1,736, mean 13.9 to 39.5
- zero fraction 0.078 to 0.213 (median 0.157): the beam-stop shadow plus
  dark-noise pixels
- 1,261 to 3,025 distinct values per frame; 3,958 to 296,603 pixels above
  255 (0.40 % of all pixels) and 443 to 3,344 above 1,000 per frame
- zlib level-1 ratio 0.41 to 0.48

Series 20180316_032-131 and 20180317_008-097 have a brighter diffuse halo
(mean 26 to 40, versus 14 to 24 for the others). Detector, geometry, beam
stop and acquisition settings are identical; the brighter halo is
crystal-to-crystal variation in diffuse scattering, not a different regime.

## Homogeneity and exclusions

All frames come from one entry, one microscope, one camera, one crystal
form and one acquisition protocol. Every header is identical apart from
`PHI`/`OSC_START` (each frame's own angle) and the per-series beam centre:
`DISTANCE=3064`, `PIXEL_SIZE=0.051`, `OSC_RANGE=1`, `TIME=5.72`,
`WAVELENGTH=0.025071`. The sibling entry EMPIAR-10319 (the same peptide at
120 kV) is deliberately not merged: a different voltage and wavelength
changes the diffraction geometry and the dose regime, so it would be a
separate family.

## Caveats

- Frames are sparse and low-count: mostly small background values with rare
  strong Bragg peaks. This is genuine diffraction material with a skewed
  distribution, not hollow storage.
- Only 3.4 % of the deposited bytes are fetched, so 24 frames out of 713.
  Neighbouring frames within a series are similar, so the selection keeps
  the three frames of a series 20 to 34 degrees apart.
- `EXPECTED_OUTPUT_DIGEST` in `scripts/microed_smv.py` pins the SHA-256
  over the 24 (sample name, sample SHA-256) lines from the first build
  (`efa1456a...a73d`); build and verify both enforce it. The chain behind
  it is the central-directory SHA-256 pins, then the member CRC-32s, then
  the SMV header SHA-256 pins.
