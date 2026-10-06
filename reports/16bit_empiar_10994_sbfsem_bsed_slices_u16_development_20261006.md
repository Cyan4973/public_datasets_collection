# EMPIAR-10994 raw SBF-SEM BSED slices uint16 development

## Outcome

Accepted `empiar_10994_sbfsem_bsed_slices_u16`. It holds raw serial block-face SEM backscattered-electron (BSE) block-face images of two resin-embedded HeLa cells in metaphase: a control cell and a REEP3/4-knockdown cell. Each sample is the native 16-bit Gatan DigitalMicrograph (DM4) image array of one 30 nm slice. It is emitted unchanged at its native frame size.

This is the first 16-bit SBF-SEM family in the corpus. The same imaging modality is already accepted at 8 bits as `empiar_13192_sbfsem_vessel_slices_u8`. That recipe is a different EMPIAR entry, lab, instrument (Thermo VolumeScope), specimen (mouse vessel) and pixel size (65 nm), and is natively uint8. The novelty here is therefore labelled a new source, not a new modality. The other 16-bit electron-microscopy families are MicroED diffraction frames (`empiar_10318_microed_diffraction_frames_u16`) and TEM projections (`zenodo_tem_tilt_series_i16`).

## Source and rights

- Source: EMPIAR-10994 (Belevich & Jokitalo; Kumar et al. 2019, Mol Biol Cell 30:1377), released 2024-01-16, DOI 10.6019/EMPIAR-10994
- Imagesets used:
  - `data/160621_HeLa_Control/01_original_images`: 578 DM4 files
  - `data/161107_HeLa_REEP3-4_KD_LBR/01_original_images`: 474 DM4 files
  - EMPIAR declares both imagesets UNSIGNED 16 BIT INTEGER
- Not used: `02_processed_dataset` (aligned, contrast-normalized 8-bit TIFF) and `03_models`
- Access: anonymous HTTPS from `ftp.ebi.ac.uk/empiar/world_availability/10994/`
- License: CC0 1.0. The EMPIAR FAQ states: "All data in EMPIAR is freely and publicly available to the global community under the CC0 license". `download.sh` re-fetches the FAQ and fails if that sentence is missing.
- Personal data: none. The DM4 metadata contains an operator e-mail-alert address; it is never emitted.

## Shape and conversion

- Instrument: Gatan 3View with the 3VBSED detector on an FEI Quanta, 2016
- Acquisition: 30 nm cuts, 20 µs dwell, 14.8–15.3 nm pixels, 2.5 kV (control) and 2.4 kV (KD)
- Runs: each cell was acquired as six consecutive runs that differ only in ROI size:
  - control: r01a 26, r01b 83, r01c 132, r01d 131, r01e 85, r01f 121 slices
  - KD: r01 105, r01b 72, r01c 82, r01d 17, r01e 114, r01f 84 slices
- Exclusion: KD r01d slices 0014–0016 (200 V, 100.8 nm calibration, a beam fault). The depositors deleted exactly these frames from their processed stack (Amira header `MIB: Delete slice: 274:276`). This leaves 578 + 471 valid slices.
- Selection: every 8th valid slice per cell in acquisition order (240 nm apart), giving 73 control and 59 KD slices. All 12 runs are represented.
- Decoding: `scripts/dm4.py` is a pure-stdlib DM4 tag-tree walker. It checks big-endian structure, u64 tag lengths against type descriptors, exact nesting, the zero trailer and that root length equals size − 24. It locates `ImageList[1]/ImageData/Data`, with descriptor `[20, 4 (uint16), w*h]`, DataType 10 and PixelDepth 2.
- Output: the 2·w·h little-endian value bytes, written unchanged with shape `[height, width]`. No alignment is assumed; 131 of the 132 arrays start at odd offsets.
- Per-file assertions: thumbnail-first two-entry ImageList; detector, microscope, voltage, slice thickness, dwell, DigiScan size, calibration, acquisition date, and image name and 3View path matching the run and slice.
- Pins: size, data offset, dimensions, calibration, voltage, acquisition time, metadata-skeleton SHA-256 and whole-file SHA-256.

## Accepted output

- Primary samples: 132 (73 control, 59 KD)
- Per run:
  - control: 4/10/17/16/11/15
  - KD: 14/9/10/2/14/10
- Shapes: 76 × 1400², 27 × 1500², 14 × 1280², 15 × 1096 rows × 1200 columns
- Primary values: 252,375,600
- Primary bytes: 504,751,200
- Median sample: 1,960,000 values
- Download: 537,980,563 pinned DM4 bytes (93.8% kept)
- Value range: 8,454–38,610, with no 0 or 65535 values
- Distinct values per frame: 6,710–16,950
- Maximum modal fraction: 0.00066
- zlib level-1 ratio: 0.826–0.861
- Per-cell brightness offset:
  - control frame means: 24.9k–27.5k
  - KD frame means: 32.5k–34.8k
  - same count unit, tick and noise scale
- Output digest: `9197d1b64aac0f49910a52dbf772625e538cedb17358473d87c2216654250453`

## Judge checks

- Gate: `python3 tools/autocollect/gate.py staging/empiar_10994_sbfsem_bsed_slices_u16` returned PASS with no warnings and the numbers above.
- verify.sh: I ran it myself from `/tmp/autocollect/<id>/`; it passed. It re-derived all 132 frames from the DM4 files, byte-compared each sample, recomputed stats and index rows, checked the sample directory against the index and the manifest counts, and matched the pinned digest. `selftest` also passed. build.sh only reads local downloads; there is no network code in build or verify.
- Bytes: I read 11 samples across both cells and all shapes with `array('H')`.
  - Low-4-bit histogram max/min is 1.01–1.03 and the odd fraction is 0.500, so there is no lattice or widening.
  - Neighbour step is 560–770 counts against an SD of about 1,000, a correlation of about 0.6.
  - Consecutive selected slices correlate at 0.27–0.34, against 0.64–0.68 between rows within a frame, so they are not near-duplicates.
  - Downsampled PNG renders show correctly decoded mitotic HeLa cells (chromosomes, ER, mitochondria), including the 1096×1200 frames, with no shear.
- Bitshift tag: 6 on 130 frames. The two exceptions are each cell's first frame (5 and 4), and neither shows an intensity jump, so the tag is metadata only.
- Detector settings: STEM-detector Bright/Contrast and Frodo brightness and bias are identical in all files. Only voltage and spot size differ between cells.
- Rights: I fetched the EMPIAR FAQ myself and confirmed the CC0 sentence verbatim. No credentials appear in any script, and no metadata strings are emitted.
- Novelty: novelty.py with the entry and FTP URLs and EM terms found only `empiar_13192_sbfsem_vessel_slices_u8` as same-modality (different source, 8-bit), plus unrelated EMPIAR and backscatter families. There were no downstream hits.
- Scope arithmetic: ceil(578/8) = 73 and ceil(471/8) = 59. KD r01d slices 14–16 are 1-based stack indices 274–276, matching the Amira deletion.
