# EMPIAR-10318 200 kV MicroED diffraction frames uint16 development

## Outcome

Accepted `empiar_10318_microed_diffraction_frames_u16`. It holds native 16-bit electron-diffraction detector frames from the eight continuous-rotation MicroED series in EMPIAR-10318, which are FUS(37-42) SYSGYS peptide nanocrystals on an FEI Tecnai F20 at 200 kV.

This is the first rotation-series spot-diffraction detector-frame family in the local corpus, and nothing comparable exists downstream. The closest local families are different:
- `zenodo_silicon_diffraction_tiff_u16`: one SEM backscatter Kikuchi (EBSD) pattern.
- `zenodo_powder_xrd_patterns_f32`: 1-D powder curves.
- `wwpdb_structure_factors_f32`: reduced reflection tables.
- The existing EM image families are real-space TEM, SBF-SEM and segmentation material.

## Source and rights

- **Source:** EMPIAR entry EMPIAR-10318, DOI 10.6019/EMPIAR-10318, deposited 2019-09-19, released 2021-06-09. Served anonymously from `https://ftp.ebi.ac.uk/empiar/world_availability/10318/data/`.
- **Imageset:** one SMV imageset, 8 ZIP archives (one per crystal), 10,167,940,116 bytes in total. They hold 713 `D520mm_NNNN.img` frames (100, 61, 100, 90, 90, 99, 82, 91 per series) plus one `.cec` beam-centre sidecar per archive.
- **Acquisition:** wavelength 0.025071 Å; each frame is a 1° wedge exposed for 5.72 s (0.0572 e/Å² per frame).
- **Downloaded:**
  - each archive's central directory and end records: 70,645 bytes, SHA-256 pinned;
  - 24 exact local-header-plus-DEFLATE member ranges: 341,983,518 bytes, pinned by offset, length, CRC-32, rotation angle and SMV-header SHA-256.
- **Licence:** CC0 1.0. The EMPIAR FAQ states "All data in EMPIAR is freely and publicly available to the global community under the CC0 license". `download.sh` re-fetches the FAQ and fails if that sentence disappears.
- **Safety:** synthetic hexapeptide crystals, with no human or animal material. Metadata is validated and never emitted.

## Shape and conversion

Each natural record is one SMV diffraction image: a 512-byte ASCII header followed by a 4096x4096 little-endian `unsigned_short` raster (33,554,944 bytes).

The recipe works as follows:
1. Parse the ZIP local header using its own lengths. Local extra is 0, while the central directory carries a 32-byte NTFS extra.
2. Raw-inflate to exactly 33,554,944 bytes and check the CRC-32.
3. Validate the SMV header: exact key set and order, HEADER_BYTES=512, TYPE=unsigned_short, BYTE_ORDER=little_endian, SIZE1=SIZE2=4096, DISTANCE=3064, OSC_RANGE=1, WAVELENGTH=0.025071, TIME=5.72. PHI must equal the pin, and the beam centre must be constant within a series.
4. Emit bytes 512.. unchanged as one 4096x4096 uint16 sample.

There is no crop, mask, rescale or tiling. Seven archives carry ZIP64 end records although every offset fits in 32 bits; these are validated, and no ZIP64 sizes are needed.

Selection keeps positions `floor(n*(2k+1)/6)` (the 1/6, 1/2 and 5/6 points) of every series, so all 8 crystals are equally represented and rotation angles run from -50 to +35°. The cap fits at most 29 of the 713 frames.

EMPIAR's imageset label says `SIGNED 16 BIT INTEGER`, but every header says `unsigned_short`. Realized values never exceed 32,767, so the two readings give the same bytes. The header's 51 µm pixel and 3064 mm distance are depositor-set labels that imitate an ADSC Q210; they are not a rescaling. The 120 kV sibling entry EMPIAR-10319 is excluded as a different regime.

## Accepted output

- Primary samples: 24 (3 per series x 8 series)
- Values per sample: 16,777,216 (median 16,777,216)
- Primary values: 402,653,184
- Primary bytes: 805,306,368
- Download bytes: 341,983,518 member ranges + 70,645 central-directory bytes (+ ~51 KB metadata pages)
- Global range: 0..32,747; pixels above 32767: 0
- Per-frame maxima: 10,141 to 32,747; medians: 7 to 19; p99: 114 to 331; p99.99: 391 to 1,736
- Per-frame mean: 13.9 to 39.5 (two series, 032-131 and 008-097, have a brighter diffuse halo)
- Zero fraction: 0.078 to 0.213 (median 0.157), and zero is also the modal value
- Distinct values per frame: 1,261 to 3,025
- Pixels above 255: 3,958 to 296,603 per frame (0.40 % overall); above 1,000: 443 to 3,344
- Constant rows or columns: 0; unique payloads: 24
- zlib level-1 ratio: 0.409 to 0.484
- Output digest: `efa1456a2c4eb3e31054d1a6c96c0fa15ca84c223288bc8c69efc4723227a73d`

## Judge checks

- `gate.py` passed with no warnings: 402,653,184 values, 805,306,368 bytes, 24 samples, widths [16].
- I ran `verify.sh` myself and it exited 0, matching the pinned output digest. `build.sh` uses only local files, and grep shows curl only in `download.sh` and `discover.sh`, with no credentials. The driver download log shows all 24 members validated and 341,983,518 range bytes inventoried.
- Independent decode: my own `struct` + `zlib` parse of 20180317_865-955/D520mm_0940 and 20180316_144-204/D520mm_0174 gave a matching CRC-32, a clean end of stream, and bytes 512.. equal to the emitted samples. The inflated headers read as described.
- Histograms (6 frames): values are contiguous with no comb. There is a zero spike from clipped dark noise and the beam stop, then a smooth Poisson-like decay peaking at 5 to 7 counts. The even-value fraction of 0.54 to 0.59 is explained by the zero spike.
- Spatial structure: previews (16x16 max- and mean-pooled) show the same beam-stop shadow and detector geometry in every frame. Bragg lattice rows are specific to each crystal and angle. The brighter-halo series differ only in diffuse intensity.
- Peaks are real reflections: the top-12 pixels per frame sit in multi-pixel spots with neighbours of 10k to 30k. Pixels above 5000 never recur at the same position in 3 or more frames (3,822 unique positions), so they are not hot pixels.
- Not near-duplicates: within a series only 6.9 to 10.1 % of pixels match between selected frames (MAD 11 to 16), against 5.0 % across series.
- Rights: I read the CC0 sentence in both the downloaded FAQ and the live page; it covers all EMPIAR data and lists no exceptions.
- Novelty: `novelty.py` runs on the data URL and on the diffraction, MicroED, SMV, Pilatus, Eiger, CBF and crystallography terms found no detector-frame diffraction family locally, in the registry, in the ledger or downstream.
- Volume: 24 of 713 frames is a cap-driven, crystal-balanced subset, within the ~20-sample guidance. The output is larger than the download because members are DEFLATE-compressed. The 805 MB size matches the accepted EMPIAR-13192 precedent of whole natural frames.
