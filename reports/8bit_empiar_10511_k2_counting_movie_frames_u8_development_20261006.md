# EMPIAR-10511 K2 electron-counting movie frames uint8 development

## Outcome

Accepted `empiar_10511_k2_counting_movie_frames_u8`. It holds 40 native 8-bit dose-fractionated cryo-EM movie frames recorded on a Gatan K2 Summit direct electron detector in counting mode (FEI Titan Krios, 300 kV). They come from EMPIAR-10511, mouse cGAS bound to nucleosomes from HEK 293T cells. Each sample is one unnormalized detector frame of per-pixel electron counts.

This is a new modality for the corpus: sparse, near-Poisson electron-count frames with a mean of about 0.87 e/pixel/frame and about 1.8 bits/value of histogram entropy. The nearest existing families are all dense images or diffraction patterns:

- `zenodo_tem_tilt_series_i16`: integrated TEM projections;
- `empiar_10318_microed_diffraction_frames_u16`: integrating-camera diffraction;
- `empiar_13192_sbfsem_vessel_slices_u8` and `empiar_10994_sbfsem_bsed_slices_u16`: SBF-SEM backscatter;
- the 8-bit EBSD and SPED pattern families.

No counting-mode or cryo-EM movie material exists locally, in the registry or ledger, or downstream.

## Source and rights

- Source: EMPIAR entry EMPIAR-10511, DOI 10.6019/EMPIAR-10511, released 2020-10-09. Served anonymously from `https://ftp.ebi.ac.uk/empiar/world_availability/10511/data/`.
- Imageset: one imageset of 2,979 unaligned multiframe MRC movies, 40 frames each, `UNSIGNED BYTE`, 3838x3710 at 1.07 Å/pixel, 1.70e12 bytes in total.
- Excluded: `gain-reference.mrc`, a float32 correction map.
- Acquisition facts: from EMDB EMD-22047 (48 e/Å² total exposure, defocus 0.8–2.0 µm). They are cited only; nothing is fetched from EMDB.
- Licence: CC0 1.0. The EMPIAR FAQ states "All data in EMPIAR is freely and publicly available to the global community under the CC0 license". `download.sh` re-fetches the FAQ and fails if the sentence disappears. Three accepted EMPIAR recipes rest on the same basis.
- Safety: the specimen is purified recombinant protein–nucleosome complexes. The entry JSON, which lists depositor contact details, is used only for validation and is never emitted.

## Shape and conversion

Each movie is an MRC2014 stack written by Gatan DigitalMicrograph GMS 3.23:

- a 1024-byte little-endian header;
- NSYMBT = 0 and MAPC/MAPR/MAPS = 1/2/3;
- 40 contiguous mode-0 sections of 3838x3710.

The natural record is one section, i.e. one dose fraction. For each of 40 movies, chosen at bin centres `floor((2s+1)*2979/80)` of the name-sorted listing (indices 37 … 2941), the recipe range-fetches two pieces:

- the header: bytes 0–1023;
- section z = 20: bytes 284,780,624–299,019,603.

Every response must be a 206 with the exact Content-Range over 569,560,224 bytes.

Pins, per movie:

- file size;
- header SHA-256;
- SHA-256 of the 64 KiB frame prefix;
- SHA-256 of the whole frame;
- one output digest over all samples.

The header is fully validated. Its DMIN/DMAX/DMEAN describe the first frame only, so frames are compared with DMEAN alone. The frame bytes are emitted unchanged as one 3710x3838 row-major uint8 raster.

MRC2014 defines mode 0 as signed int8, while EMPIAR declares unsigned. Build and verify require max ≤ 127, so both readings are identical. The realized maximum is 80. Hot pixels are kept as acquired.

## Accepted output

- Primary samples: 40
- Values per sample: 14,238,980 (median 14,238,980)
- Primary values: 569,559,200
- Primary bytes: 569,559,200
- Range-fetched bytes: 569,600,160
- Frame means: 0.8247–0.9899 e/pixel (median 0.8743), each within 0.18 % of the header DMEAN
- Zero fraction: 0.372–0.440 (0 is the modal value in every frame)
- Pooled value shares: 0: 41.79 %, 1: 36.32 %, 2: 15.93 %, 3: 4.70 %, 4: 1.05 %, ≥5: 0.22 %; >10: 7.4e-7
- Per-frame entropy: 1.727–1.875 bits (median 1.774)
- Distinct values per frame: 16–24
- Hot values (≥16) per frame: 3–14; frame maxima 31–80
- zlib level-1 ratio: 0.327–0.342 (median 0.332)
- Constant rows or columns: 0
- Unique payloads: 40
- Acquisition span: 2020-03-04T15:49:40 to 2020-03-05T12:25:17. Templates 3403802/3403820/3403812/3403658 contribute 12/10/9/9 frames.
- Output digest: `1f736f4887d93b62c74579e725e7b50a3c9c3f30ab03a433d73d83787e353926`

## Judge checks

- **Gate:** `gate.py` passed with no warnings.
- **Verify:** I ran `verify.sh` myself and it exited 0: 40 samples and 569,559,200 bytes verified, global range [0, 80], pinned output digest reproduced.
- **Local build, credentials:** `build.sh` reads only local files. No script contains credentials.
- **Driver download:** the download log records 40 validated frames and range_bytes = 569,600,160.
- **Headers:** I parsed them with my own `struct` code and got NX/NY/NZ/MODE 3838/3710/40/0, MX/MY/MZ equal to the frame geometry, MAPC/R/S 1/2/3, ISPG/NSYMBT 0/0, `MAP ` with stamp 0x4441, and one label `Digital Micrograph(TM), GMS v 3.23`.
- **Byte identity:** spot-checked samples (slots 5, 22, 38) are byte-identical to the downloaded frame ranges.
- **Bytes (slots 0, 13, 27, 39):**
  - var/mean is 1.005–1.009;
  - P0/P1/P2 match Poisson at the frame mean to within about 0.2 percentage points;
  - horizontal and vertical neighbour correlation is −0.009 to −0.002;
  - 4x4 block means show a smooth 0.82–0.99 gain/ice gradient whose orientation differs between movies;
  - hot pixels recur at fixed detector coordinates across different movies, e.g. (1770, 721), (3361, 3033), (2201, 3759), which confirms a consistent frame grid and offset;
  - byte agreement between slots 0 and 13 is 0.3374, against 0.3366 expected for independent frames, so there are no near-duplicates.
- **Builder's stats:** I recomputed the pooled histogram, entropy, distinct-value, hot-value, maximum, zlib and DMEAN-deviation figures from `ingest_stats.json`, and all match the builder's claims.
- **Rights:** I fetched the EMPIAR FAQ live and confirmed the CC0 sentence under "Under what license is EMPIAR data available?". The entry JSON carries no per-entry licence or restriction field.
- **Novelty:** `novelty.py` (EMPIAR 10511 URL; terms counting, movie frame, cryo-EM, K2 Summit, direct electron, dose-fractionated, micrograph, MRC, Gatan) found only other EMPIAR entries of different modality and generic term hits. Downstream has nothing.
- **Caveats:**
  - This is the fourth EMPIAR-sourced family and the fourth EM-adjacent 8-bit family accepted in this effort, though it is a statistically distinct regime.
  - 40 samples is under the soft "50+" guidance. It was accepted because each frame is 14.2 MB and the family is already about 5.7x the downstream sub-sample size.
