# EMPIAR-10511 Cryo-EM Gatan K2 Electron-Counting Movie Frames (3838x3710, MRC mode 0) UInt8

- Candidate id: `empiar_10511_k2_counting_movie_frames_u8`
- Width: uint8
- Quantity: Per-pixel electron counts in individual dose-fractionated cryo-EM movie frames: unnormalized K2 counting-mode detector output, mean about 0.93 e/pixel/frame, range 0-36
- Source: https://www.ebi.ac.uk/empiar/EMPIAR-10511/
- Resources: https://www.ebi.ac.uk/empiar/api/entry/EMPIAR-10511/, https://ftp.ebi.ac.uk/empiar/world_availability/10511/data/, https://ftp.ebi.ac.uk/empiar/world_availability/10511/data/FoilHole_3402467_Data_3403658_3403660_20200304_153825-257811.mrc, https://www.ebi.ac.uk/empiar/faq
- License: CC0-1.0
- License evidence: https://www.ebi.ac.uk/empiar/faq
- License quote: "All data in EMPIAR is freely and publicly available to the global community under the CC0 license" (EMPIAR FAQ, re-checked live 2026-10-06; same basis as the accepted empiar_13192_sbfsem_vessel_slices_u8).
- Natural record: One dose-fractionated detector frame: 3838x3710 uint8 counts (14,238,980 values), i.e. one z-section of a 40-frame MRC movie stack. Frames are contiguous after the 1024-byte header (NSYMBT = 0), so each frame is one range request. Whole movies are 569.6 MB, so a frame-level bounded subset is needed to cover many exposures.
- Estimated samples: 40
- Estimated primary values: 569,559,200
- Estimated download bytes: 569,600,160
- Estimated primary bytes: 569,559,200
- Decode path: Range GET bytes 0-1023 of each chosen .mrc. Parse with struct '<4i' at offset 0 and require nx=3838, ny=3710, nz=40, mode=0, NSYMBT(offset 92)=0. Pin file size 569,560,224. curl Range [1024 + k*14238980, 1024 + (k+1)*14238980) for the chosen frame k (e.g. frame 20). The bytes are uint8 counts emitted as-is; pure-stdlib checks are length, max under 255, and a non-degenerate histogram. Suggested subset: one fixed-index frame from each of 40 movies evenly spaced over the 2,979-movie listing.
- Novelty kind: new_modality
- Novelty evidence: novelty.py on the EMPIAR 10511 URL and the terms counting/'movie frames'/cryo-EM found no URL, registry, ledger or downstream match; the only hits are BBBC 16-bit microscopy on 'counting'. The existing EMPIAR families are SBF-SEM backscatter slices (u8 and u16) and MicroED diffraction frames (u16): dense images or diffraction, not sparse Poisson electron-count frames. No electron-counting movie data exist at any width locally or downstream.
- Homogeneity: One entry, one microscope session/detector (K2 counting, GMS 3.23), and identical geometry for 2,979 movies (3838x3710x40, mode 0, all 543 MiB). One specimen type (mouse cGAS-nucleosome complexes). Taking one fixed frame index per movie keeps the dose position consistent.
- Risks: (1) Structural biology, outside this round's focus domains. It is the second 8-bit EMPIAR-sourced family, though a different modality from SBF-SEM. (2) Low dynamic range: values 0-36 and entropy about 1.8 bits/value. That is native for counting detectors, and 8 bits is the narrowest standard width. (3) MRC2014 defines mode 0 as signed int8, while EMPIAR declares 'UNSIGNED BYTE'; values are non-negative counts at most 36, so this is harmless but should be documented. (4) One 54 MB file in the directory deviates from the rest, so pin exact sizes. (5) Samples are large (14.2 MB each).
- Probe evidence: HEAD shows Accept-Ranges: bytes and Content-Length 569,560,224. A 1-byte range GET returned 206. Header: nx 3838, ny 3710, nz 40, mode 0, NSYMBT 0, label 'Digital Micrograph(TM), GMS v 3.23', stored min/max/mean 0/36/0.926; expected size equals the actual size. A 61 KB chunk of frame 20 histogrammed as 0:24285, 1:22487, 2:10530, 3:3225, 4:706, 5:140, 6:32, 7:3 (mean 0.928, entropy 1.82 bits). The EMPIAR API lists 2,979 movies x 40 frames, UNSIGNED BYTE, 1.5 TB; the directory listing shows 2,979 files of 543M. The FAQ CC0 sentence is present.

Proposed by the autocollect scout on 2026-10-06 (transcript `.data/pipeline/logs/scout_8bit/scout.20261006_023706.jsonl`).
