# CGRO BATSE CONT LAD count spectra int16 development

## Outcome

Accepted `nasa_heasarc_batse_cont_counts_i16` after one text-only repair cycle.

The recipe collects the native `BATSE_CNTS.COUNTS` column from 50 CONT daily files. These are 2.048 s, 16-channel count spectra from the eight NaI(Tl) Large Area Detectors (LADs) of the Burst And Transient Source Experiment on NASA's Compton Gamma Ray Observatory, 1991–2000.

It is a new quantity for the corpus: binned multichannel gamma-ray scintillator count spectra. The nearest local family, `nasa_heasarc_nicer_pi_i16`, is on the same HEASARC host but holds per-photon X-ray PI channel event lists from a different mission and detector.

The first judge pass found the data sound but the documentation factually wrong in several places:
- converter version and date
- an undisclosed alternate channel ladder
- calibration-row counts and rows-per-era figures

The repair corrected all of these, and the builder found a fourth non-standard ladder (TJD 8395). Sample bytes, selection and totals did not change.

## Source and rights

- Source: NASA HEASARC archive, anonymous S3 mirror `https://nasa-heasarc.s3.amazonaws.com/compton/data/batse/daily/`. The S3 listing has 3,317 `cont_*.fits.gz` keys covering 3,315 unique TJDs (8362–11690), 24.9 GB in total.
- Selection: 50 objects, each pinned by key, exact size, S3 ETag (43 single-part MD5s and 7 two-part composites), NAXIS2 and SHA-256. The sources.tsv sha256 is `5c12e219d08b7163e8a58df2abefa763b68ea5df4b167524e4ae41062332d05e`.
- Download: 377,862,785 bytes.
- Provenance:
  - S3 LastModified is 2023-07-10 for 40 keys and 2023-08-02 for 10.
  - Five MSFC converter versions wrote the files: `CONT_DISCLA_FITS` 4.10 ×7, 1.01 ×3, 2.05 ×14, 3.00 ×1 and 2.06 ×25, all FILE-VER V1.00.
- License basis: NASA SMD Open Scientific Data Policy, the same basis as the accepted NICER recipes. Supporting evidence:
  - All 50 primary headers carry ORIGIN 'MSFC' and OBSERVER 'G. J. Fishman', so these are NASA Marshall products.
  - The official NASA Images and Media Usage Guidelines say NASA content "generally are not subject to copyright in the United States" and that "NASA is committed to transparency, open science, and making data available to everyone". Both quotes are verbatim in the copies pinned by the accepted WMAP and TESS recipes.
  - NASA's AI conditions are recorded in `[safety].usage_notes`: no attribution of output to NASA, no implied endorsement, no insignia in training.
- Caveat: the SMD policy page and www.nasa.gov were proxy-blocked on 2026-10-05, so the SMD wording is carried over from the NICER manifests rather than re-fetched.

## Shape and conversion

- Natural record: one CONT daily file.
- Sample: the whole COUNTS column in native row order, shape `[rows, 16 channels, 8 detectors]` with the detector index varying fastest. This follows the FITS column-major TDIM (8,16).
- Source column: TFORM7 `128I`, TUNIT `COUNTS`, with no TZERO, TSCAL or TNULL. The only transformation is a big-endian to little-endian byte swap.
- Not emitted: MID_TIME, position, DEADTIME, FLAGS and pointing columns, and the DISCLA, DISCSP, HER and SHER products.
- Selection rule: 50 evenly spaced TJD targets, each snapped to the nearest day with a file of at least 5 MB and at least 20,000 rows. Only TJD 8729 was skipped, for 8730.
- Missing values: none. All 323 negative words are kept as stored: wraps past 32767 during bright episodes plus isolated glitch words. So are the 93,694 values ≥4096 (0.05%, almost all in contiguous bright episodes) and one all-zero row.
- Homogeneity: the stored quantity is the same throughout. Four days use non-standard channel ladders according to their own BATSE_E_CALIB tables:
  - TJD 8395: early-mission ladder with a populated channel 0
  - TJD 10126: rotated ladder, with channel 0 at about 1.8 MeV
  - TJD 10992 and 11058: fine low-energy ladder
- On those days the unit, 2.048 s lattice, schema and magnitude range are unchanged. Gain drift is documented: detector 7's channel-5 lower edge goes from 70 keV to 84.7 keV over 1998–2000.

## Accepted output

- Primary samples: 50 (TJD 8395, 1991-05-19, through TJD 11658, 2000-04-24)
- Rows: 1,496,816
- Primary values: 191,592,448 int16
- Primary bytes: 383,184,896
- Minimum sample: 2,560,128 values (TJD 9261, 20,001 rows)
- Median sample: 3,966,976 values
- Maximum sample: 4,795,008 values (TJD 8528, 37,461 rows)
- Value range: -32,765 to 32,702
- Negatives: 323; values ≥4096: 93,694; zeros: 128
- Aggregate SHA-256 of the samples concatenated in path order: `53b765725cdd77f75f44e835fe47610eee158515572c964b60da4bd3ed305e41`

## Judge checks

- `python3 tools/autocollect/gate.py staging/nasa_heasarc_batse_cont_counts_i16`: PASS, no warnings.
- `bash staging/nasa_heasarc_batse_cont_counts_i16/verify.sh`: rc=0, all 50 samples verified.
- I grepped `build.sh`, `verify.sh` and `scripts/*.py` for network calls. Only the discovery-time `select_days.py` uses curl; build and verify read local files only.
- I wrote my own FITS header and binary-table parser (`/tmp/autocollect/batse_judge2/`) and ran it on all 50 gzip files. For every sample:
  - Byte equality with the `>128h` words at row offset 28: confirmed for all 50.
  - Negative and ≥4096 counts match the index on every day.
  - No row repeats its predecessor on any day.
  - Median MID_TIME spacing is 2.048 s on every day.
- Repaired claims, re-measured from the headers and calibration tables:
  - MNEMONIC, DATE and CDATE inventory, including the card comment "Date FITS file created"
  - BATSE_E_CALIB rows (8–112) and the CAL_NAME split (2.02 ×7, 1.1 ×10, 2.01 ×33)
  - mid-day channel edges for the four non-standard-ladder days
  - per-channel medians and peaks: channels 3–4 on standard days, 9 on TJD 10126, 14 on TJD 10992 and 11058, 2 on TJD 8395
  - detector-7 channel-5 drift (70.0 to 84.7 keV)
  - rows-per-era table
- I parsed the saved ListObjectsV2 pages: the pinned keys, sizes and ETags all match, and LastModified splits 40 on 2023-07-10 and 10 on 2023-08-02.
- The pinned NASA guideline HTML files match their recorded sha256 values, and I found both quotes verbatim along with the AI-applications conditions.
- novelty.py on the S3 prefix and the terms batse, cgro, compton, gamma-ray, large area detector and scintillator: only self-matches, plus an unrelated MAGIC f64 hit on 'gamma-ray'.
