# EMPIAR-13192 Carotid2 Serial Block-Face SEM Backscatter Slices UInt8

This recipe collects 32 native 8-bit block-face images from one serial block-face
scanning electron microscopy (SBF-SEM) volume in EMPIAR-13192 ("Volume electron
microscopy reveals heterogeneity of the hemostatic response in veins and
arteries", Stalker lab, Thomas Jefferson University; DOI 10.6019/EMPIAR-13192).
The volume is imageset Carotid2: a hemostatic plug formed after puncture injury
of a mouse carotid artery, imaged on a Thermo Fisher (FEI) VolumeScope. It has
1250 slices at a 200 nm z-step, and each slice is a 6144x4096 frame with 65 nm
pixels.

## Licence

The EMPIAR FAQ (<https://www.ebi.ac.uk/empiar/faq>) states: "All data in EMPIAR
is freely and publicly available to the global community under the CC0
license". `download.sh` fetches the FAQ and fails if that sentence disappears.

## What is collected

- Slices z = 10, 50, 90, ..., 1250 (every 40th slice, so neighbours are 8 um
  apart in z), giving 32 samples that span the whole volume. The full imageset
  is 31.5 GB, far above the 1 GB cap, so it is subsampled evenly instead of
  cropping frames.
- One sample per slice: the 6144x4096 uint8 image, row-major as stored (top scan
  line first). That is 25,165,824 values per sample and 805,306,368 bytes in
  total.
- Download: 32 whole TIFFs, 806,100,140 bytes, plus the EMPIAR entry JSON and
  FAQ page.

## Decode

Each file is a little-endian classic TIFF written by the FEI xT acquisition
software:

- the 8-byte header `II*\0` points to an IFD at byte 25,165,832;
- the image occupies bytes 8 to 25,165,831 as 2048 contiguous uncompressed strips
  of 2 rows each;
- the IFD (15 tags) is followed by its out-of-line arrays and the FEI metadata
  tags 34682 (INI text) and 34683 (XML), which run to end of file.

The parser checks every one of these facts, then copies the strip bytes. The
FEI text is validated but never emitted. It is pure standard-library Python with
no dependencies.

## Why only Carotid2

The entry has six imagesets. Carotid1 has 140 nm pixels at 3072x2048, and
Jugular1 and Jugular3 have 30 nm pixels with different frame sizes and file
layouts (Jugular1 is a big-endian ImageJ-style TIFF). The screener probed
Carotid3 and Jugular2: they carry an Imaris 10.2 `[ImarisDataSet]` description
instead of FEI tags, with RowsPerStrip 1 and an Imaris ColorRange of 0-65535.
That suggests a 16-to-8-bit export rescale, not native frames. Carotid2 is the
only volume confirmed to carry untouched FEI xT frames. Mixing volumes would
mix pixel sizes and processing histories, so the family is restricted to this
one volume.

## "Aligned" label

EMPIAR names every imageset "Aligned SBF-SEM image files", and the citation
note says the micrographs are "the aligned SBF-SEM image stacks". The Carotid2
files nevertheless have these properties:

- they keep the per-slice FEI xT layout and metadata, with acquisition
  timestamps from 2022-05-24 to 2022-06-05 that rise strictly with z;
- the metadata declares `PostProcessing=None`, `Transformation=None`,
  `DriftCorrected=Off`, `DatabarHeight=0`, and a full 6144x4096 scan area;
- probes of the top and bottom 64 rows of Z0001, Z0600 and Z1250 found no
  constant padding rows or columns.

The full build found no constant row or column in any of the 32 frames. Build
and verify reject any frame that has one, so a translation-padded frame would
fail the recipe. An integer shift with wrap-around could not be detected this
way. It is considered unlikely given the untouched metadata, but it is not
ruled out.

Some edge structure is acquisition content, not padding:

- From about z = 130 to z = 1090, the top 1-6 % of the frame lies beyond the
  trimmed top edge of the resin block. The band is dark and noisy (row means
  of roughly 2-60, against about 170 for resin) and has a ragged, slightly
  tilted boundary with streaky knife/edge texture.
- The band's height changes with z. It is absent for z ≤ 90 and z ≥ 1130.
- The leftmost ~16 columns are somewhat darker than the rest of the frame
  (scan line start). At z = 1250 the top-left corner is partly clipped to 0.

These regions are real detector readings and are kept as acquired.

## Homogeneity

All 32 slices share the instrument, the 3 kV beam, the 151.6 pA beam current,
1 us dwell, 2x line integration, the 65 nm pixel size and the frame geometry.
Acquisition paused for 9 days between z = 770 and z = 810. The second session
uses slightly different detector contrast and brightness (47.5/36.9 instead of
51.5/32.3) and a working distance that differs by 0.4 um. These are the same
8-bit BSE intensity lattice and generation process, but the realized value
range differs:

- Session 1 (z ≤ 770, 20 frames) uses all 256 levels (0-255).
- Session 2 (z ≥ 810, 12 frames) tops out at 220-235, with 204-235 distinct
  levels per frame.
- zlib level-1 ratios are 0.88-0.89 in session 1 and 0.75-0.80 in session 2.

Histograms are smooth in both sessions: adjacent-bin count ratios stay within
±1.3 % across the 5th-95th percentile range. There is no comb pattern, so
there is no sign of a histogram stretch from a higher bit depth.

## Realized output

- 32 samples of 25,165,824 values each, 805,306,368 bytes in total, all 32
  payloads unique.
- Per frame: at least 204 distinct values, a modal value covering at most
  2.9 % of pixels, no constant rows or columns.
- 979,947 zero pixels in total (0.12 %), concentrated in the off-block band,
  and 312 pixels at 255.
- Output digest (SHA-256 over sample-name/hash lines):
  `6aabf0cefce281fc39d0fe24e9d7a229b3a474d34956a1c3672f72933afce1af`.
  Build and verify both enforce it.

## Pins

`discover.sh` resolved the selection with metadata-only requests: one HEAD, an
8-byte header range and a ~25 KB metadata-tail range per slice. It wrote
`scripts/carotid2_slices.tsv` with the exact size, the SHA-256 of the metadata
tail, and the acquisition timestamp for each slice. EMPIAR publishes no
checksums. The whole-file SHA-256 column started as `-` and was filled from the
first verified download (autocollect driver, 2026-10-06, `source_inventory.json`).
The downloaded Z1250 also matched, byte for byte, the header, foot and tail
ranges fetched separately during discovery. `download.sh` now enforces the
whole-file hashes on every run, and build and verify refuse to run without them.

## Run

```bash
bash staging/empiar_13192_sbfsem_vessel_slices_u8/download.sh
bash staging/empiar_13192_sbfsem_vessel_slices_u8/build.sh
bash staging/empiar_13192_sbfsem_vessel_slices_u8/verify.sh
```

All scripts honour `DATA_DIR` (default `.data`) and log to
`$DATA_DIR/logs/empiar_13192_sbfsem_vessel_slices_u8/`.
