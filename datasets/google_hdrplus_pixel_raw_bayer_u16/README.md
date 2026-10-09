# Google HDR+ Burst Dataset: Pixel/Pixel XL Raw Bayer CFA Frames (uint16)

This recipe collects 29 complete raw Bayer sensor mosaics from Google's HDR+
burst photography dataset. Each sample is the first input frame
(`payload_N000.dng`) of one burst shot on a Google Pixel (`sailfish`) or
Pixel XL (`marlin`) through the Android Camera2 RAW path. The values are
10-bit sensor digital numbers (WhiteLevel 1023, black level about 63.5-64 DN
per CFA site) on a 2x2 **BGGR** colour-filter-array lattice. They are stored
losslessly as uint16 at 4048 columns x 3036 rows, which is 12,289,728 values
(24,579,456 bytes) per frame.

| | |
|---|---|
| Samples | 29 frames, one per burst (16 `Pixel XL`, 8 `sailfish`, 5 `marlin`) |
| Primary values / bytes | 356,402,112 values / 712,804,224 bytes |
| Download | 29 DNGs, 219,795,130 bytes (sizes and MD5s pinned in `sources.tsv`) |
| Width | uint16 little-endian (10 significant bits, native storage width of the DNG) |
| Natural record | one complete raw frame (all 192 LJ92 tiles, cropped to the image) |

## Source and license

- Dataset page: <https://hdrplusdata.org/dataset.html>
- Bucket README: <https://storage.googleapis.com/hdrplusdata/README.html>. The
  bucket is anonymous and not requester-pays.
- License: **CC BY-SA 4.0**. The README says: *"The dataset is released under a
  Creative Commons license (CC-BY-SA). This license is broad and largely
  unencumbered, however our main intention is that the dataset be used for
  scientific purposes."* The license link points to
  <https://creativecommons.org/licenses/by-sa/4.0/>. Derived outputs (these
  decoded mosaics) inherit CC BY-SA 4.0 and must carry attribution.
- Citation (requested by the authors):
  Samuel W. Hasinoff, Dillon Sharlet, Ryan Geiss, Andrew Adams, Jonathan T.
  Barron, Florian Kainz, Jiawen Chen, Marc Levoy. *Burst photography for high
  dynamic range and low-light imaging on mobile cameras.* ACM Transactions on
  Graphics (Proc. SIGGRAPH Asia) 35(6), 2016.

## Privacy

The README says GPS tags were stripped, and that *"the subjects of the
dataset include the authors' friends and family, so please keep usage in good
taste."* To respect this, the 40 evenly spaced candidate bursts were reviewed
using the EXIF thumbnails embedded in the dataset's own gallery JPEGs
(`scripts/gallery_thumbs.sh`). Any burst showing a real person was excluded:
portraits, hikers, cafe or street scenes, and visitors in the background. That
removed 11 bursts. The 29 kept scenes are landscapes, architecture, plants,
objects, food, and one museum photo of a 19th-century painting.
`privacy_screen.tsv` records the verdict and a short note for every reviewed
burst. The samples contain only CFA pixel values. No EXIF or maker metadata is
copied into them, and the index stores only the camera model, capture
timestamp, CFA/black/white levels and the Orientation tag.

## Selection (homogeneity)

`discover.sh` enumerated all 3640 bursts of the full release
(`20171106/bursts/`) through the GCS JSON API (`matchGlob=**/payload_N000.dng`,
`pageToken` pagination). It range-read 4 KiB of every N000 frame and parsed
TIFF IFD0. The results:

- 1504 frames have IFD0 at the end of the file (legacy uncompressed DNG writer, older Nexus bursts) and are excluded.
- 1316 frames are not Google-made: 466 Nexus 6P, 195 Nexus 6, 89 Nexus 5, 14 angler, 3 Nexus 5X, and 549 with no Make tag.
- 161 Pixel frames have other dimensions and are excluded: 136 are 4048x3044, and 25 are 3280x2464 (digitally zoomed or pre-cropped).
- **659 frames pass** `check_pixel_cfa`: Make google, Model sailfish/marlin/Pixel/Pixel XL (the later HDR+ firmware writes the retail names for the same two phones), NewSubFileType 0, Photometric 32803, Compression 7, BitsPerSample 16, 4048x3036, 256x256 tiles x 192, WhiteLevel 1023, BGGR, no LinearizationTable, no SubIFDs.

Sorting the 659 by burst folder name and taking 40 evenly spaced picks gives
the candidate set. The privacy screen then leaves 29. Only one frame per burst
is collected (N000), never several near-duplicate frames from the same burst.
The pinned list is `sources.tsv`, with burst, model, CFA, size, GCS MD5, GCS
generation and URL. `download.sh` fetches only these 29 objects.

Because all frames come from one sensor (Sony IMX378), with one readout
geometry, one bit depth, one black/white level regime and one CFA phase, the
family is a single compression regime. Black levels vary slightly per frame
(63.0-64.0 DN per site). That variation comes from the camera and is kept.

## Conversion

The DNG IFD0 holds the full-resolution CFA image as 192 tiles of 256x256.
Each tile is an ITU-T T.81 lossless-JPEG (SOF3) stream with 16-bit precision,
2 interleaved components x 128 columns x 256 rows, predictor 1, and point
transform 0. `scripts/hdrplus_dng.py` is a pure-stdlib decoder. It handles:

- Huffman DC tables (16-bit lookup tables, SSSS 0..16)
- predictors 1-7 per T.81 H.1.2.1
- point transform and restart intervals

It then puts each tile's two components back into 256-pixel rows, places the
tiles row-major, crops the right and bottom edge tiles to 4048x3036, and
writes raw little-endian uint16. There is **no** black subtraction,
linearization, white balance, lens-shading correction, demosaicing,
normalization or rotation. Orientation=6 is recorded in the index but not
applied, so samples are in sensor readout order.

Checks:

- `scripts/selftest_lj92.py` runs before every build and verify. It
  round-trips synthetic streams through a reference encoder: all 7
  predictors, 1/2/4 components, precisions 10/12/16, point transform 2,
  restart intervals, and full-range differences including SSSS=16. It also
  decodes a synthetic tiled CFA DNG with cropped edge tiles.
- The decoder was checked on a real Pixel frame. Min 61 sits just under the
  63.5 black level, the two G sites have equal means (consistent with BGGR),
  and there are no tile-seam discontinuities. A rendered thumbnail showed a
  clean scene.
- `build.sh` fails on any value above WhiteLevel, any constant or duplicate
  frame, or a source whose MD5 has changed.
- `verify.sh` recomputes min, max and SHA-256 and checks the 0..1023 range,
  black-level sanity (p0.1 >= 40, median >= 60) and the number of distinct
  values. It re-decodes five tiles per frame, including the right-edge,
  bottom-edge and corner tiles, using its own tile placement arithmetic, and
  compares them pixel for pixel. It also checks the manifest totals and
  `ingest_stats.json`.

## Running

```bash
bash staging/google_hdrplus_pixel_raw_bayer_u16/download.sh   # ~220 MB, resumable
bash staging/google_hdrplus_pixel_raw_bayer_u16/build.sh      # ~5-8 s per frame
bash staging/google_hdrplus_pixel_raw_bayer_u16/verify.sh
```

`discover.sh` and `scripts/gallery_thumbs.sh` document how `sources.tsv` was
derived. They are not part of the acceptance path. The privacy review step is
a human judgement, recorded in `privacy_screen.tsv`.

## Caveats

- 29 of the 659 eligible Pixel bursts are collected. That is about 713 MB,
  well inside the 1 GB cap; downstream sub-samples about 100 MB per family.
- Scenes skew toward outdoor California landscapes from a few photographers
  (burst prefixes 0043 and 0155 dominate).
- The privacy screen used about 160x120 thumbnails. Small incidental figures
  could in principle be missed, although none were seen in the kept set. The
  residential-street scene shows parked cars; plates are not legible at
  thumbnail size and may be partly legible after demosaicing at full
  resolution.
- Realized build (29 frames): global min 0, global max 1023. 21 frames reach
  WhiteLevel (saturated highlights). Most frame minimums are 61-64. Eight
  frames have isolated sub-black photosites, with minimums 0, 0, 13, 30, 36,
  49, 50 and 51. In the four frames inspected, 6 to 411 pixels per frame
  read below 45 DN. They are never more than 3 per row, and their same-colour neighbours read normally (about 60-90 DN).
  This is consistent with read noise and defective pixels in a raw that has
  had no defect correction. They are native values and are kept. In every
  frame the two G sites have equal means, which is the BGGR signature.
  zstd -3 compresses one frame from 24.6 MB to about 10.9-11.1 MB (about
  2.2-2.3x).
- verify.sh re-decodes tiles with the same `decode_lj92` used by the build.
  Only the tile placement and crop arithmetic are independent. Decoder
  correctness rests on the synthetic round-trip self-test and on the
  real-frame sanity checks below.
- Pre-download end-to-end check, run in scratch on one real Pixel frame
  (`20171106_subset/bursts/0006_20160722_115157_431/payload_N000.dng`, not part
  of the pinned set): build 5.4 s, min 61 / max 814, CFA site means
  81.5/90.2/90.3/75.8 (the G sites agree, consistent with BGGR), p0.1 63,
  median 69. verify and `tools/autocollect/gate.py` passed. A downsampled
  render showed a clean, seam-free scene (rotated, because Orientation=6 is not
  applied).
