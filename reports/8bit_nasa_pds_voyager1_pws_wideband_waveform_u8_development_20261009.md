# Voyager 1 PWS wideband waveform uint8 development

## Outcome

Accepted `nasa_pds_voyager1_pws_wideband_waveform_u8`. These are raw electric-field waveform codes from the Voyager 1 Plasma Wave Subsystem (PWS) waveform receiver:
- 4-bit linear codes 0-15, after a 40 Hz-12 kHz bandpass and an automatic gain control (AGC);
- sampled at 28,800 samples/s in 1600-sample lines;
- covering the 1978 Earth-Jupiter cruise, the Jupiter and Saturn encounters, the outer-heliosphere cruise, the heliosheath and the interstellar medium (to 2023).

This is the corpus's second plasma-wave waveform family at 8 bits, after `nasa_pds_cassini_rpws_wbr_10khz_waveform_u8`. The novelty is new content in a known modality: a different spacecraft, receiver and volume on the same UIowa PDS host, with a 4-bit AGC code lattice instead of Cassini's 8-bit DN. The measured breadth verdict is OK. The nearest family is downstream `cov_cover_type` (distance 0.0788, loss 0.0765), then local `covertype_uci:cov_col_55` (0.0801 / 0.0765). `noaa_isd_lite:isd_day` compresses about as well (loss -0.0081) but is statistically far (0.0897). The Cassini WBR and MIT-BIH ECG families are not among the 10 nearest.

## Source and rights

- Source: NASA PDS Planetary Plasma Interactions Node, University of Iowa, `https://space.physics.uiowa.edu/plasma-wave/voyager/data/VGPW_1001/`, data set `VG1-J/S/SS-PWS-1-EDR-WFRM-60MS-V1.0`. The volume was reissued 2024-07-26; its AAREADME header reads "PRERELEASE".
- Pinned bytes:
  - 322,394,112 bytes in 400 DAT frames;
  - 2,753,860 bytes in 400 detached labels;
  - 1,547,057 evidence bytes: AAREADME.TXT, CATALOG/DATASET.CAT, DOCUMENT/DATATIPS.TXT, WFROWPFX.FMT, INDEX/INDEX.LBL and INDEX/INDEX.TAB.
- Every file is pinned by exact size and by the upstream MD5 from `EXTRAS/MD5LF.TXT`. DAT SHA-256 is recorded in `download_plan.tsv` at download time and re-checked by build and verify.
- License: NASA SMD open scientific data policy. Information produced from SMD-funded research is to "be made publicly available". The volume AAREADME imposes no restriction and only encourages acknowledging the PDS and the instrument PIs; download.sh greps that sentence. This is the same basis as the accepted `nasa_pds_cassini_rpws_wbr_10khz_waveform_u8` and `nasa_pds_voyager_iss_saturn_raw_u8`.

## Shape and conversion

Each natural record is one archived 48-second frame `Cmmmmmnn.DAT` (one SCLK mod-60 count). It holds a 1024-byte engineering header record, then up to 800 1024-byte line records. Each line record is a 220-byte big-endian row prefix, 800 bytes of packed 4-bit samples and 4 spare bytes.

For each frame the recipe:
- checks the label: DATA_SET_ID, VG1, PRODUCT_ID and START_TIME equal to the pin, RECORD_BYTES 1024, START_BYTE 221, START_BIT 1, ITEM_BITS 4, OFFSET -7.5, VALID 0-15, 0.00003472222 s interval, and FILE_RECORDS x 1024 = DAT size;
- requires the header ASCII at byte 249 to read `VOYAGER-1 PWS`;
- walks records 2..N and drops:
  - records whose FDS_LINE_COUNT (MSB u16, bytes 23-24) is out of range or out of order;
  - all-zero waveform records (archive fill);
  - waveform records identical to the last kept line (the documented 5x repetition after 1992-11-03);
- unpacks bytes 229-1020 of each kept line high nibble first into 1584 codes. The first 16 samples are dropped on every frame, following DATASET.CAT's note that they are invalid during the Jupiter encounter;
- writes the concatenated codes unchanged as `<PRODUCT_ID>.u8`.

Selection: all 11,415 INDEX.TAB frames are sorted by START_TIME and split into eight strata from the DATASET.CAT event table. Picks sit at evenly spaced ranks. A pick with fewer than 512 records is replaced by the next rank (33 replacements).

| stratum | interval | pool | picks |
|---|---|---|---|
| A pre-Jupiter | 1978-08 to 1979-02-27 | 562 | 40 |
| B Jupiter | 1979-02-28 to 1979-03-22 | 6,490 | 100 |
| C Jupiter-Saturn | 1979-03-23 to 1980-11-10 | 121 | 30 |
| D Saturn | 1980-11-11 to 1980-11-16 | 41 | 20 |
| E full-rate cruise | 1980-11-17 to 1992-11-02 | 579 | 70 |
| F decimated cruise | 1992-11-03 to 2004-12-15 | 1,005 | 50 |
| G heliosheath | 2004-12-16 to 2012-08-24 | 809 | 40 |
| H interstellar | 2012-08-25 to 2023-11-07 | 1,808 | 50 |

## Accepted output

- Pinned frames: 400, 1978-09-26T12:05 to 2023-07-24T12:39. Frames excluded: 0.
- Data records walked: 314,438.
  - Kept lines: 228,022.
  - Repeat records dropped: 86,416 (F/G/H only).
  - Zero-fill and bad-line records: 0.
- Primary samples: 400.
- Primary values and bytes: 361,186,848 (= 228,022 x 1584).
- Minimum sample: 198,000 values (125 lines). Median: 1,252,944 (upper median; gate mean-of-middle 1,252,152). Maximum: 1,267,200 (800 lines).
- Per stratum (samples / values):
  - A 40 / 49,983,120
  - B 100 / 126,594,864
  - C 30 / 37,917,792
  - D 20 / 25,188,768
  - E 70 / 87,272,064
  - F 50 / 12,209,472
  - G 40 / 9,806,544
  - H 50 / 12,214,224
- Code histogram (0..15): 860,372 / 709,345 / 1,449,372 / 4,565,972 / 10,435,629 / 19,022,273 / 43,759,989 / 90,988,649 / 106,430,381 / 42,323,146 / 21,587,816 / 11,473,742 / 4,804,529 / 1,488,154 / 662,708 / 624,771.
- Aggregate order-0 entropy: 2.82 bits. Code 8 holds 29.5% of all values. Per-frame mode share is 0.12-0.54.
- Aggregate sample SHA-256: `9e1c0b134296bcd741ec4aa34d169e8d2f1b87876006d22774ea339d269f981d`.
- Breadth (zlsim): OK. Own ratio 6.39; zlsim mode_share 0.464; nearest `cov_cover_type` at 0.0788 / 0.0765.

## Judge checks

- `python3 tools/autocollect/gate.py staging/nasa_pds_voyager1_pws_wideband_waveform_u8`: PASS, no warnings.
- `bash staging/.../verify.sh`, re-run by the judge, printed `verify ok samples=400 excluded=0 bytes=361186848 median=1252944` with all 8 strata and all 16 codes. verify.py does not import the build module: it re-implements the record walk, line rule and unpack, byte-compares every sample, and checks SHA-256 plus the upstream MD5.
- build.py and verify.py read only local files; download.sh is curl-only with no credentials.
- Independent stdlib scans:
  - Nibble order: high-nibble-first gives the smoother waveform in all 16 frames checked, two per stratum (mean |delta| 0.13-1.28 vs 0.23-1.89 for low-first). The builder also reports a byte-exact match against the volume's reference `TESTOUT.TXT`.
  - First 8 bytes per line: zero in 800/800 lines of B-stratum frames, real data in A and C-H, matching DATASET.CAT.
  - Repeats: the post-1992 frames contain exactly 21,604 identical 5-record runs. The 6 singleton lines in VG1P04C5720201 differ from their neighbours in 727-750 of 800 bytes, so they are genuine, not near-duplicates.
  - Label DATA_LINES equals the non-fill record count in all 400 labels. This contradicts DATASET.CAT's "unique lines" wording but matches the README's statement.
  - Signal: per-stratum mean lag-1 autocorrelation 0.82-0.97 and order-1 entropy 0.73-1.33 bits, an oversampled band-limited waveform. Long constant runs of 0 or 15 are mostly clipping at the ends of ramps.
- Novelty and rights:
  - `novelty.py --url` matched the same host only, via the Cassini recipes. The `--type`/`--instrument`/`--archive` query returned 1/0/0 (Cassini WBR). There is no Voyager PWS entry locally or downstream.
  - Read the pinned AAREADME (acknowledgement request only, no restriction text) and fetched the NASA SMD policy page via curl ("be made publicly available").
- Non-blocking notes:
  - 80 of 228,022 kept lines end in partial zero fill, apparently mid-line dropouts: 50,629 codes, 0.014%. They are kept as code 0, consistently in build and verify.
  - The AAREADME marks VGPW_1001 "PRERELEASE". The MD5 pins make any upstream re-issue fail loudly.
  - The builder's phrase "most common code is 46.4% of all values" is zlsim's mode_share metric. In the aggregate histogram code 8 holds 29.5%.
