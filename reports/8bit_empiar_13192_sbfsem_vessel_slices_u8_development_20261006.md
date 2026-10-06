# EMPIAR-13192 Carotid2 SBF-SEM backscatter slices uint8 development

## Outcome

Accepted `empiar_13192_sbfsem_vessel_slices_u8`. It holds native 8-bit backscattered-electron block-face images from one serial block-face scanning electron microscopy (SBF-SEM) volume in EMPIAR-13192, imageset Carotid2. That volume is a mouse carotid-artery hemostatic plug imaged on a Thermo Fisher (FEI) VolumeScope.

This is the first electron-microscopy family at 8-bit in the local corpus. It is also new relative to the downstream corpus and the registry: the existing 8-bit microscopy is light microscopy only (`bbbc007_fluorescence_u8`), and the existing EM families are 16-bit TEM projections or segmentation volumes.

## Source and rights

- Source: EMPIAR entry EMPIAR-13192, DOI 10.6019/EMPIAR-13192, released 2026-02-24, served anonymously from `https://ftp.ebi.ac.uk/empiar/world_availability/13192/data/Stalker_SBF-SEM/Carotid2/`.
- Imageset: Carotid2, 1250 slices, each 6144x4096 pixels at 65 nm, with a 200 nm z-step. The API declares the voxel type `UNSIGNED BYTE`.
- Downloaded: 32 whole TIFFs, 806,100,140 bytes in total. Each is pinned by exact size, SHA-256 of the metadata tail, FEI acquisition timestamp (strictly increasing with z), and whole-file SHA-256.
- Licence: CC0 1.0. The EMPIAR FAQ states "All data in EMPIAR is freely and publicly available to the global community under the CC0 license". `download.sh` re-fetches the FAQ and fails if that sentence disappears.
- Safety: the material is mouse tissue. The FEI metadata holds only the generic `Supervisor` account and the instrument PC name. It is validated but never emitted.

## Shape and conversion

Each natural record is one block-face acquisition: one FEI xT little-endian classic TIFF. The file layout is:

- an 8-byte header pointing to an IFD at byte 25,165,832;
- 2048 contiguous uncompressed 2-row strips starting at byte 8;
- one trailing IFD of 15 tags, whose out-of-line arrays and FEI INI/XML tags (34682 and 34683) run to end of file.

The parser validates the full layout and tag set, then checks the FEI invariants:

- Volumescope, 6144x4096, 65 nm pixels, 3 kV;
- a single `VS DBS` BSE detector;
- `PostProcessing=None`, `Transformation=None`, `DriftCorrected=Off`, `BitShift=0`, no data bar;
- full-frame ScanArea.

It then emits the strip bytes unchanged as one row-major uint8 sample of 4096x6144 pixels. There is no rescaling, cropping or remapping.

The selection is every 40th slice, z = 10, 50, …, 1250. The 32 samples are 8 µm apart and span the whole volume. The other five imagesets are excluded because their pixel size, frame size or processing history differ (Carotid3 and Jugular2 are Imaris exports).

Acquisition paused for 9 days between z = 770 and z = 810. The second session uses different detector contrast and brightness (47.5/36.9 instead of 51.5/32.3):

- Session 1 (20 frames) spans 0–255 with standard deviation 44–49.
- Session 2 (12 frames) tops out at 220–235 with standard deviation 26–40.

Instrument, beam, dwell time, pixel size, digital mapping (`DigitalContrast=-1`, gamma 1) and generation process are identical. The family is therefore treated as one acquisition regime with a detector gain change.

## Accepted output

- Primary samples: 32
- Values per sample: 25,165,824 (median 25,165,824)
- Primary values: 805,306,368
- Primary bytes: 805,306,368
- Download bytes: 806,100,140
- Distinct values per frame: at least 204
- Largest modal fraction: 0.0286
- Constant rows or columns: 0
- Unique payloads: 32
- Zero pixels: 979,947 (0.12 %, mostly in the dark off-block band at the top of z = 130–1090); pixels at 255: 312
- zlib level-1 ratio: 0.745–0.893 (median 0.884)
- Acquisition span: 2022-05-24T13:08:12 to 2022-06-05T13:05:56
- Output digest: `6aabf0cefce281fc39d0fe24e9d7a229b3a474d34956a1c3672f72933afce1af`

## Judge checks

- `gate.py` passed with no warnings.
- I ran `verify.sh` myself and it exited 0: 32 samples and 805,306,368 bytes verified, with the pinned digest.
- `build.sh` uses only local files. No script contains credentials.
- The `download.sh` cache-hit validator (`check-file`) accepted all 32 local files against the pinned whole-file SHA-256 values. The driver download log records the 806,100,140-byte fetch.
- I parsed the TIFF IFDs with my own `struct` code and reassembled the strips from StripOffsets/StripByteCounts. The result equals every emitted sample byte for byte.
- Histograms:
  - no comb: even/odd bin mass ratio 0.99–1.01;
  - deviation from the neighbour average at most 1.3 % across the 5–95th percentiles;
  - bimodal shape (tissue and resin), as expected.
- Alignment and padding:
  - the column-to-column difference profile peaks at no more than 1.25x its median, so there is no seam;
  - the only row-difference spike is at the off-block boundary near row 205;
  - the scan-start gradient at x = 0–32 and the brighter row 0 sit in the same place in all 32 frames.
  - So the EMPIAR "aligned" label reflects acquisition-time stage tracking (StageX steps of 5 µm), not a post-hoc shift.
- Diversity: consecutive frames correlate 0.77–0.97 at a 4 µm block scale, which is structural continuity. The most similar pair (z = 850 and z = 890) shares only 2.0 % identical pixels, with a mean absolute difference of 17.4.
- Metadata diff across all 32 files: only detector contrast/brightness (a single session switch), stigmator, working distance, beam shift, stage tracking, pressure and currents vary. `DigitalContrast`, `DigitalGamma` and `DigitalBrightness` are constant.
- Rights: I fetched the EMPIAR FAQ myself and confirmed the CC0 sentence. The entry JSON carries no per-entry restriction.
- Novelty: `novelty.py` (URL and terms EMPIAR, SBF-SEM, block-face, FIB-SEM, volumescope) and `--list-width 8` show no electron microscopy at 8-bit locally, in the registry, in accepted ledger rows, or downstream.
