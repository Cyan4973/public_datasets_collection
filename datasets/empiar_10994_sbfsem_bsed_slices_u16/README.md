# EMPIAR-10994 raw SBF-SEM BSED slices — uint16

Raw serial block-face scanning electron microscopy (SBF-SEM) images of two
HeLa cells in metaphase, deposited by the University of Helsinki Electron
Microscopy Unit as EMPIAR-10994 (Kumar et al. 2019, *Mol Biol Cell*
30:1377). A Gatan 3View ultramicrotome inside an FEI Quanta SEM cut the
resin block 30 nm at a time, and the 3VBSED backscatter detector imaged each
fresh block face. DigitalMicrograph saved each image as one DM4 file. Pixel
size is about 15 nm.

Each sample is one block-face image: the native little-endian `uint16`
detector intensities from the DM4 file, unchanged, at that run's native frame
size.

## Licence

EMPIAR FAQ (<https://www.ebi.ac.uk/empiar/faq>): "All data in EMPIAR is
freely and publicly available to the global community under the CC0 license".
`download.sh` re-fetches the FAQ and fails if that sentence disappears.
Please cite DOI 10.6019/EMPIAR-10994 and the associated paper.

## Scope and selection

The two raw imagesets hold 1052 DM4 files (about 4.1 GB), more than the corpus
cap allows. Each cell was acquired as six consecutive runs. The runs differ
only in field of view: the operator resized the region of interest between
runs.

| cell | run (slices, frame size, pixel) | selected |
|---|---|---|
| control (2.5 kV) | r01a 26, r01b 83 (1280², 15.34 nm); r01c 132 (1400², 14.92 nm); r01d 131, r01e 85 (1500², 14.99 nm); r01f 121 (1096×1200, 15.19 nm) | 73 |
| REEP3/4 KD (2.4 kV) | r01 105, r01b 72, r01c 82, r01d 17, r01e 114, r01f 84 (all 1400², 14.82 nm) | 59 |

KD r01d slices 0014–0016 are excluded. Their DM4 metadata report 200 V and a
100.8 nm calibration, and their intensities jump to about 40k: a beam fault.
The depositors removed exactly these frames from their processed stack; the
Amira header of `02_processed_dataset` records `MIB: Delete slice: 274:276`,
1-based. That leaves 578 + 471 valid slices.

Within each cell, slices are ordered by acquisition (run order, then slice
number), and every 8th valid slice is kept: z_index 0, 8, 16, and so on. That
is 240 nm between kept slices, and every run is represented in proportion to
its length. Adjacent 30 nm slices are near-duplicates, so a contiguous block
was not taken. Result: 132 samples, 252,375,600 values, 504,751,200 bytes,
from 537,980,563 downloaded bytes.

Not used: `02_processed_dataset`, which is aligned, contrast-normalized
8-bit TIFF, and `03_models` segmentations.

## Decoding

DM4 is a tag tree. Structure fields are big-endian, with u64 tag lengths;
values are little-endian, per the header flag. `scripts/dm4.py` is a pure-stdlib
walker. It checks that every tag length matches its type descriptor and nests
exactly within its parent. Large arrays are located, never decoded.
`ImageList[0]` is the RGBA thumbnail; `ImageList[1]/ImageData/Data` is the
image, an array `[20, 4 (uint16), width*height]`.

The Data array starts wherever the preceding tags end. In 131 of the 132
selected files it starts at an odd byte offset, so no alignment is assumed.
On a real file, the correct decode has a mean neighbour step of about 680
counts; decoding one byte off gives about 21,800, which is noise.

Per file, the recipe asserts:

- DataType 10, PixelDepth 2, element type uint16, count = width × height
- a thumbnail-first two-entry ImageList
- detector 3VBSED, FEI Quanta, the cell's voltage, 30 nm slice thickness and 20 µs dwell
- a ~15 nm square calibration in µm
- the cell's acquisition date
- an image name and 3View base path that match the run and slice
- the pinned size, Data offset, dimensions, calibration, voltage,
  acquisition time and metadata-skeleton SHA-256

The `DigiScan/Bitshift` tag varies (4–6) within runs without any change in
intensity scale, so it is ignored.

`scripts/empiar10994.py selftest` builds synthetic DM4 files and checks:

- exact decoding with the Data array at both odd and even offsets
- struct, string and struct-array tags
- sparse-range parsing
- rejection of uint8 or RGB main images, count mismatches, the beam-fault
  metadata, wrong runs or slices, corrupted lengths and constant frames

The self-test runs at the start of download, build and verify.

## Scripts

```bash
bash staging/empiar_10994_sbfsem_bsed_slices_u16/discover.sh   # metadata only; regenerates the pin table
bash staging/empiar_10994_sbfsem_bsed_slices_u16/download.sh   # ~538 MB, resumable
bash staging/empiar_10994_sbfsem_bsed_slices_u16/build.sh
bash staging/empiar_10994_sbfsem_bsed_slices_u16/verify.sh
```

`discover.sh` checks the live listings against the 12-run structure. It
records the entry, licence and Amira evidence, then resolves each pin from a
HEAD request plus about 160 KB of byte ranges per file, without reading the
image arrays. Whole-file SHA-256 pins were recorded from the verified
2026-10-06 download; they and the output digest
`9197d1b64aac0f49910a52dbf772625e538cedb17358473d87c2216654250453` are
enforced.

## Realized output

132 samples, 252,375,600 uint16 values, 504,751,200 bytes:

- shapes: 76 at 1400², 27 at 1500², 14 at 1280², 15 at 1096×1200
- no 0 or 65535 values
- 6,710–16,950 distinct values per frame
- zlib level-1 ratio 0.83–0.86, because shot noise dominates

The two cells use different detector brightness windows. Control frames
average 24.9k–27.0k counts (overall 8,454–30,912); KD frames average
32.7k–34.7k (25,207–38,610), with fewer distinct values. Same detector,
units and acquisition process, but expect a cell-dependent offset.

## Relation to other recipes

`empiar_13192_sbfsem_vessel_slices_u8` is the same imaging modality
(SBF-SEM block-face backscatter). It differs in width (native uint8), source,
instrument (Thermo VolumeScope), specimen (mouse vessel) and pixel size
(65 nm). `zenodo_tem_tilt_series_i16` is 16-bit, but it is transmission EM
projection imagery. No 16-bit scanning or volume-EM block-face family exists
locally.
