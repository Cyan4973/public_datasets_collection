# nmrXiv P90 (Swertia chirayita extracts) Bruker 600 MHz 1H zg30 Free-Induction Decays: Native TopSpin-4 DTYPA=2 Float64 Time-Domain Data

- Candidate id: `nmrxiv_p90_bruker_1h_fid_f64`
- Width: float64
- Quantity: Raw digitized complex NMR free-induction decay (interleaved real/imaginary receiver samples, arbitrary units) from the Bruker 'fid' file. acqus gives DTYPA=2 (IEEE float64), BYTORDA=0 (little-endian), TD=65536, NUC1=1H, PULPROG=zg30, BF1 of about 600 MHz.
- Source: https://nmrxiv.org/project/P90
- Resources: https://s3.uni-jena.de/nmrxiv/production/archive/2d828808-0317-48fe-8679-813f91101b2e/nmr-data-of-ethanolic-extract-and-fractions-of-swertia-chirayita.zip, https://nmrxiv.org/api/v1/list/projects?page=1&per_page=100
- License: CC-BY-4.0
- License evidence: https://nmrxiv.org/api/v1/list/projects?page=1&per_page=100
- License quote: "identifier":"NMRXIV:P90" ... "license":{"title":"Creative Commons Attribution 4.0 International (CC BY 4.0)","spdx_id":"CC-BY-4.0","url":"https://creativecommons.org/licenses/by/4.0/legalcode"}
- Natural record: One 1D FID: one Bruker experiment directory's fid file, holding 65,536 float64 values (32,768 complex points).
- Estimated samples: 167
- Estimated primary values: 10,944,512
- Estimated download bytes: 60,000,000
- Estimated primary bytes: 87,556,096
- Decode path: Stdlib only. Do not fetch the 1.52 GB project zip. Read its central directory with two curl range requests (EOCD in the last 64 KB, then the CD), pick the members '<exp>/fid' whose sibling acqus says DTYPA=2, NUC1=<1H>, PULPROG=<zg30>, TD=65536, and range-fetch each local header plus its deflate payload (about 330 KB). Inflate with zlib.decompressobj(-15) and decode with struct.unpack('<65536d'), using BYTORDA from acqus. Validate that the size is 524,288 bytes and the values are finite. I tested the CD parse, acqus extraction and fid inflate+decode on P56 and P90 members.
- Novelty kind: new_modality
- Measurement type: nmr_free_induction_decay
- Instrument line: bruker_600mhz_topspin4_1h_zg30
- Archive collection: nmrxiv
- Novelty evidence: novelty.py --url nmrxiv.org/project/P90 gives no matches. The term 'bruker' matches only icraf_afsis1_soil_mir_spectra_f32 (an FTIR absorbance spectrum, 32-bit). The vocabulary has no NMR or free-induction-decay type at any width, and --type nmr_free_induction_decay --archive nmrxiv returns 0. A decaying complex oscillation sum on a 2^-7 fixed-point lattice with magnitudes up to about 2.6e9 does not resemble the existing f64 families.
- Homogeneity: Single project, single 600 MHz spectrometer, single pulse program (zg30), single nucleus (1H), identical TD/DTYPA. Tally of all acqus files: 152 zg30 FIDs written by TopSpin 4.0.5 and 15 by TopSpin 4.0.3. The builder may keep only the 152 TopSpin 4.0.5 FIDs for a stricter regime. Exclude the 81 noesyigld1d (water-suppression) 1D FIDs, the 13C deptqgpsp FIDs (DTYPA=2 but another nucleus) and all 2D ser files (DTYPA=0, int32).
- Risks: (1) The values sit on a 1/128 lattice. In one decoded P90 FID, 60% of samples (the small-amplitude tail) are f32-exact and 40% need more than 24 mantissa bits (max 2.6e9). This is the instrument's native DTYPA=2 output, not a widening, but the judge may examine it. (2) The download depends on HTTP range support on s3.uni-jena.de (verified 206) and on a pinned zip size (1,519,545,194 bytes), with no member checksum beyond the zip CRC32. The builder should check CRC32 from the CD. (3) It is one project. 167 samples clears the guidance, but the primary output is only about 88 MB. (4) The first ~76 points are the Bruker digital-filter group delay, which is native content and should be left as is.
- Probe evidence: The API list shows P90 with CC-BY-4.0 and samples_count 76. HEAD on the zip gives content-length 1519545194. The CD parse found 255 'fid' members, all 524,288 bytes. Tallying every acqus: 152x 'TopSpin 4.0.5 BF1=600 DTYPA=2 1H zg30 TD=65536', 15x 'TopSpin 4.0.3 ... zg30', and 81x noesyigld1d. One range-fetched fid (10043_M04/proton_04/fid) inflated to 65,536 doubles: 467 integral, 65,515 distinct, max |x| 2.586e9. One-byte range GET returned 206.

Proposed by the autocollect scout on 2026-10-08 (transcript `.data/pipeline/logs/scout_64bit/scout.20261008_231914.jsonl`).
