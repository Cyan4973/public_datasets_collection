# EMPIAR-10318 200 kV MicroED Continuous-Rotation Electron-Diffraction Frames of FUS(37-42) SYSGYS Crystals, SMV UInt16

- Candidate id: `empiar_10318_microed_diffraction_frames_u16`
- Width: uint16
- Quantity: Electron counts on a 4096x4096 CMOS detector per 1° rotation frame of a nanocrystal electron-diffraction series (sparse Bragg spots on low background), native little-endian unsigned 16-bit
- Source: https://www.ebi.ac.uk/empiar/entry/10318/
- Resources: https://www.ebi.ac.uk/empiar/api/entry/EMPIAR-10318/, https://ftp.ebi.ac.uk/empiar/world_availability/10318/data/, https://ftp.ebi.ac.uk/empiar/world_availability/10318/data/20180316_144-204.zip, https://ftp.ebi.ac.uk/empiar/world_availability/10318/data/20180316_032-131.zip
- License: CC0 1.0
- License evidence: https://www.ebi.ac.uk/empiar/faq
- License quote: Under what license is EMPIAR data available? All data in EMPIAR is freely and publicly available to the global community under the CC0 license ( https://creativecommons.org/share-your-work/public-domain/cc0/ ).
- Natural record: One SMV .img file = one diffraction frame (512-byte text header plus 4096x4096 uint16 = 33,554,944 bytes) from one continuous-rotation series. 8 series (one ZIP each, 61-100 frames, about 713 frames total), stored as deflate members of 0.8-1.5 GB ZIPs.
- Estimated samples: 24
- Estimated primary values: 402,653,184
- Estimated download bytes: 345,000,000
- Estimated primary bytes: 805,306,368
- Decode path: download.sh: per ZIP, HEAD for length, range-GET the 64 KB tail (EOCD; CD about 6 KB, no ZIP64 since the archives are under 2 GB). Then range-GET the local header plus deflate data (about 14.3 MB) of 3 evenly spaced .img members per series (skip the .cec sidecar), pinning names, CRCs and sizes. build.sh (stdlib): zlib.decompressobj(-15) to exactly 33,554,944 bytes and check zlib.crc32. Parse the SMV header between '{' and '}' as KEY=VALUE; and require HEADER_BYTES=512, TYPE=unsigned_short, BYTE_ORDER=little_endian, SIZE1=SIZE2=4096. Emit bytes 512.. as 16,777,216 little-endian uint16 unchanged.
- Novelty kind: new_modality
- Novelty evidence: novelty.py --url https://ftp.ebi.ac.uk/empiar/world_availability/10318/data/ --terms MicroED 'electron diffraction' SMV: zero recipe, registry, ledger or downstream hits. Locally the closest is one EBSD Kikuchi pattern (zenodo_silicon_diffraction_tiff_u16, single sample, SEM backscatter). No transmission electron or X-ray diffraction frame family exists at any width, and no accepted 16-bit family in this effort is a diffraction pattern.
- Homogeneity: One EMPIAR entry, one 200 kV microscope and detector, uniform SMV headers (PIXEL_SIZE 0.051, DISTANCE 3064, OSC_RANGE 1.0, WAVELENGTH 0.025071 Å), one crystal system (FUS SYSGYS). The 8 rotation series are independent crystals under identical settings. Do not merge the sibling 120 kV entry EMPIAR-10319 (different voltage and wavelength regime); it could be a separate family later.
- Risks: Sample count is capped by the 1 GB limit at about 24-29 large frames. Values are concentrated in the low range (background 0-120 observed near the frame edge) with sparse high Bragg peaks: genuine detector counts but low entropy per pixel. EMPIAR metadata says 'SIGNED 16 BIT INTEGER' while the SMV header says unsigned_short, so follow the header and assert it per frame. Each frame needs a range request into a large ZIP.
- Probe evidence: Data directory lists 8 ZIPs (20180316_032-131 1.5G, _144-204 831M, _517_616 1.3G, _721_810 1.1G, 20180317_008-097 1.3G, _198-296 1.3G, _424-505 1.1G, _865-955 1.1G). HEAD on 20180316_144-204.zip: Content-Length 871,730,744. The 64 KB tail range gave EOCD with 62 entries (CD 6,014 bytes at 871,724,708): one D520mm_0144.cec (501 B) plus D520mm_0144..0204.img, each method 8 (deflate), compressed about 14.3 MB, uncompressed 33,554,944. A 400 KB range of member 1 was inflated with zlib(-15): header '{ HEADER_BYTES= 512; DIM=2; BYTE_ORDER=little_endian; TYPE=unsigned_short; SIZE1=4096; SIZE2=4096; PIXEL_SIZE=0.051000; ... OSC_RANGE=1.000000; WAVELENGTH=0.025071; ...', first 588,153 pixels decoded as uint16 with values 0..120. EMPIAR FAQ and policies state CC0 for all EMPIAR data. No prior registry or ledger rows.

Proposed by the autocollect scout on 2026-10-06 (transcript `.data/pipeline/logs/scout_16bit/scout.20261005_234311.jsonl`).
