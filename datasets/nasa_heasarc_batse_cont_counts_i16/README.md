# CGRO BATSE CONT daily LAD count spectra (int16)

Native signed-int16 photon-count tables from the Burst And Transient Source
Experiment (BATSE) on NASA's Compton Gamma Ray Observatory (CGRO, 1991-2000).
Every 2.048 s, each of the 8 NaI(Tl) Large Area Detectors (LADs) accumulated
counts in 16 pulse-height channels spanning roughly 20 keV to 2 MeV. The CONT
daily file holds one day of these accumulations as the `COUNTS` column of the
`BATSE_CNTS` FITS binary table.

## Scope

- 50 daily files, evenly spaced in Truncated Julian Day across the whole
  CONT archive: TJD 8395 (1991-05-19) through TJD 11658 (2000-04-24), with
  65-68 days between picks and 2-6 days per calendar year.
- One sample per day: the whole COUNTS column in native row order,
  shape `[rows, 16, 8]` (rows = NAXIS2, 20,001-37,461, median 30,992).
- 1,496,816 rows, 191,592,448 int16 values, 383,184,896 bytes of output;
  377,862,785 bytes downloaded (7 files above 8 MiB are S3 multipart objects).

Rows per day vary by era. Measured NAXIS2 ranges for the selected days:

| years | days | rows per day |
|---|---|---|
| 1991 | 4 | 36,319-37,461 |
| 1992-1993 | 11 | 20,001-35,713 |
| 1994-1998 | 27 | 28,738-33,786 |
| 1999-2000 | 8 | 22,358-30,403 |

I have not checked these variations against mission documentation. A day is
the archive's natural record, so days are never tiled, padded, or merged.

## Source and selection

- Archive: NASA HEASARC, anonymous S3 mirror
  `https://nasa-heasarc.s3.amazonaws.com/compton/data/batse/daily/`.
  Directory placement is irregular. For example, `cont_10000` lives under
  `10001_10100/`, and `cont_10500` and `cont_10600` are stored twice with
  identical bytes. `discover.sh` therefore pages the ListObjectsV2 listing once,
  dedupes identical copies, and `scripts/select_days.py` pins the selection in
  `sources.tsv`.
- Selection rule: 50 targets `t_k = 8362 + (k + 0.5) * 3329 / 50`. Each target
  snaps to the nearest day, with ties going to the lower TJD. That day's file
  must be at least 5,000,000 bytes, and its `BATSE_CNTS` header (read from a
  64 KiB range GET) must show NAXIS2 >= 20,000. Only TJD 8729 (19,833 rows) was
  skipped, and TJD 8730 replaced it.
- Provenance in the headers: every primary header has ORIGIN = 'MSFC',
  OBSERVER = 'G. J. Fishman' and FILE-VER V1.00. The files were written by
  five versions of the MSFC converter (MNEMONIC):

  | version | files | TJD | date card |
  |---|---|---|---|
  | `CONT_DISCLA_FITS 4.10` | 7 | 8395, 8462, 8528, 8662, 8730, 8795, 8862 | no DATE card; CDATE ("Date FITS file created") Jun-Aug 2002 |
  | `1.01` | 3 | 8595, 8928, 8995 | DATE Mar-Apr 1994 |
  | `2.05` | 14 | 9061-9860 and 10126 | DATE Nov 1995-Feb 1996 |
  | `3.00` | 1 | 9993 | no DATE card; CDATE 6-MAR-2001 |
  | `2.06` | 25 | 9927, 10060 and 10193-11658 | DATE Mar 1996-Apr 2000 |

  In the discovery listing, the S3 LastModified date is 2023-07-10 for 40
  of the selected keys and 2023-08-02 for the other 10.
- Pins per file: key, exact size, exact S3 ETag, NAXIS2, and SHA-256. The
  ETag is the content MD5 for single-part objects. For the 2-part objects it
  is the MD5 of the part MD5s plus a `-2` suffix, with an 8 MiB part size that
  was checked on a real object. S3 exposes no SHA-256, so those values were
  recorded from the first download on 2026-10-05. `download.sh`, build and
  verify all enforce them.

## Decode

Everything uses only the Python standard library (gzip, struct, array).

1. Walk the 2880-byte FITS header blocks. The HDUs are PRIMARY (no data),
   then `BATSE_E_CALIB`, then `BATSE_CNTS`, which is found by EXTNAME. The
   data offset is never hard-coded. `BATSE_E_CALIB` holds per-detector energy
   edges in 8-112 rows and is skipped. Its CAL_NAME is `ECALIB 2.02` on the 7
   v4.10 files and `ECALIB 1.1` on 10 files (8595, 8928, 8995, 9061, 9128,
   9194, 9261, 9328, 9394 and 10126). The other 33 files have `ECALIB 2.01`.
2. Assert the full 13-column schema: NAXIS1 = 336, `TTYPE7 = COUNTS`,
   `TFORM7 = 128I`, `TDIM7 = (8,16)` and `TUNIT7 = COUNTS`, with no
   TZERO7/TSCAL7/TNULL7. COUNTS starts at row byte 28, after MID_TIME (1D)
   and five 1E fields.
3. For every row, take the 256 COUNTS bytes and byte-swap the big-endian
   int16 values to little-endian. FITS TDIM is column-major, so the detector
   index varies fastest: element `channel*8 + detector`. The FITS header says
   so itself: "COUNTS(i,j) contains the counts in detector i (0 to 7) for
   channel j".

After the table, a file may contain only zero padding and, optionally,
header-only `RUN_LOG` extensions. `RUN_LOG` is an ASCII `TABLE` with NAXIS=0,
and its COMMENT cards log the 1994 FITS conversion run, for example "37379
rows of CONTINUOUS data written." Three of the 50 files have one (TJD 8595,
8928 and 8995). Its logged CONTINUOUS row count must equal NAXIS2, and any
other trailing HDU or nonzero padding is fatal.

Nothing else is emitted. MID_TIME, spacecraft position, DEADTIME, FLAGS and
pointing columns are not part of the payload. The other daily products are
excluded: DISCLA mixes discriminator, total and charged-particle counts;
DISCSP, HER and SHER use different detectors or resolution.

## Homogeneity notes

- Every value has the same meaning and unit: raw LAD counts per 2.048 s in
  one energy channel. All 8 detectors are identical instruments read out in
  one telemetry format.
- The channel energy edges are not fixed. They differ by detector and by
  calibration epoch, as the per-file `BATSE_E_CALIB` table records. Typical
  values sit in 6-11 bits. On the standard channel table (46 of the 50 days),
  the per-channel median counts per 2.048 s peak at channels 3-4. Channels
  1-5 run about 700-1,440, channels 12-14 about 100-290, and channel 0 about
  160-380.
- Gain drift: detector 7's channel-5 lower edge sits at about 70 keV through
  TJD 10925 (1998-04). It then rises to 74.6 keV at TJD 11125 (1998-11) and
  84.7 keV at TJD 11658 (2000-04). Over the same span, the smallest channel-2
  lower edge across detectors rises from 26 to 32 keV.
- Four days use a non-standard CONT channel ladder, according to their own
  `BATSE_E_CALIB` rows. The ranges below span the detectors, using the
  calibration row that covers mid-day. Several detectors have two
  calibration rows covering the same day.
  - TJD 8395 (1991-05) uses an early-mission ladder without the duplicated
    bottom edge. Detector 0's lower edges are 24, 33, 42, 56, 75, 95,
    115 ... keV, and the channel-5 lower edge is 91-98 keV instead of 70-79.
    Channel 0 is therefore a populated bin of about 20-37 keV (median about
    910 counts), but the peak stays at channels 1-3.
  - TJD 10126 (1996-01) uses a rotated ladder. Channel 0's lower edge is
    about 1.79-1.88 MeV (depending on detector and calibration row), and the
    lower edges of channels 1-15 span about 20-590 keV.
  - TJD 10992 and 11058 (1998) use a fine low-energy ladder. The channel-1,
    channel-2 and channel-5 lower edges are 20-28, 22-32 and 36-46 keV
    (detector 0: 24, 28, 33, 37, 42, 47 ... keV), and channel 15 starts at
    about 1.8 MeV.
  - On the last three days, the per-channel medians peak at channel 9 (TJD
    10126, about 1,090) or channel 14 (TJD 10992 and 11058, about 1,225),
    with channels 9-13 (TJD 10126) or 9-14 (TJD 10992 and 11058) at about
    660-1,225. On the standard table the peak is at channels 3-4.
  - These days stay in the family because the stored quantity (counts per
    2.048 s per channel), unit, 2.048 s lattice, schema and magnitude range
    are unchanged. Only the mapping from channel index to energy differs,
    and BATSE_E_CALIB records it. The emitted samples do not include that
    calibration.
- Missing values: none. COUNTS has no TNULL, and nothing is masked, clipped,
  unwrapped or dropped. Measured over all 50 days:
  - There are 323 negative words, on 19 days (1.7 per million values). They
    come in two kinds. Some are sustained runs in one detector/channel during
    very bright episodes: the count climbs smoothly past 32767 and continues
    near -32000. For example, TJD 11125 row 8185, channel 3, detector 7 reads
    31766, 32540, -31811, -31370. The true count exceeded the declared signed
    range and is stored modulo 2^16. The others are isolated one-row glitch
    words (e.g. 136, -30530, 3732).
  - The column declares signed `I` with no TZERO, so the signed reading is
    kept. A consumer can read the same bits as uint16 without loss.
  - 93,694 values (0.05%) are >= 4096. Nearly all fall in contiguous
    multi-row episodes, such as bright transients or high-background
    intervals, not isolated words: 99.4% of them sit in a row adjacent to
    another row with such a value. The count varies widely by day, from 0 to
    15,530. It is lowest in the 1996 samples (0.1 per 10k values) and highest
    in the 1991, 1994, 1998 and 1999 samples (7-10 per 10k).
  - One all-zero row (TJD 9527, row 19277) is kept as stored.
  - Per-sample `negative_count`, `spike_count` (>= 4096) and `zero_count`
    are in the index.

## Rights

The license basis is the NASA SMD Open Scientific Data Policy. In NASA SMD's
words, information produced from SMD-funded scientific research "is held as a
public trust, made publicly available, and openly shared". This is the same
basis as the accepted `nasa_heasarc_nicer_pi_i16` and
`nasa_heasarc_nicer_detector_u8` recipes.

Supporting evidence:

- Every primary header carries ORIGIN = 'MSFC' and OBSERVER = 'G. J.
  Fishman'. The products were made by the BATSE team at NASA Marshall Space
  Flight Center.
- The official NASA Images and Media Usage Guidelines
  (https://www.nasa.gov/nasa-brand-center/images-and-media/) say NASA
  content "generally are not subject to copyright in the United States". In
  their AI section they say "NASA is committed to transparency, open science,
  and making data available to everyone".
- I re-read those quotes from the copies of the page pinned by the accepted
  `nasa_wmap_healpix_sky_maps_f32` and `nasa_tess_lightcurves_f32` recipes.
  This recipe neither fetches nor depends on those files.

The same page sets conditions for AI applications, repeated in
`[safety].usage_notes`:

- Do not attribute AI output to NASA ("according to NASA" is prohibited).
- Do not imply NASA review, permission or endorsement.
- NASA insignia must not appear in AI training. The samples contain only
  count words, with no insignia or imagery.

The SMD policy page, heasarc.gsfc.nasa.gov and www.nasa.gov were
proxy-blocked from the collection environment on 2026-10-05. So the SMD
wording is carried over rather than re-fetched. The BATSE READMEs in the
bucket carry no contrary terms. The data are instrument counts with no
personal content.

## Scripts

| file | role |
|---|---|
| `discover.sh` | one-off: paged S3 listing, then `scripts/select_days.py`, which writes the `sources.tsv` candidate |
| `download.sh` | curl `-C -` with stall limits into `.part`; validates size, ETag, SHA-256, gzip, FITS identity, schema and NAXIS2; refetches an invalid cached file; writes `download_inventory.json` |
| `build.sh` | `scripts/batse_cont.py`: decode, write `samples/<id>/batse_lad_cont_counts_i16/cont_<TJD>_counts.bin`, index and `filtered/<id>/ingest_stats.json` |
| `verify.sh` | `scripts/verify_cont.py`: an independent parser that re-decodes every row with `struct`, checks byte equality and every index statistic, and checks the inventory and manifest totals |

All scripts honour `DATA_DIR` (default `.data`) and log to
`$DATA_DIR/logs/nasa_heasarc_batse_cont_counts_i16/`.
