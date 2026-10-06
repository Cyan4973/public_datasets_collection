# Magellan Venus F-MIDR SAR framelets (uint8)

Native 8-bit synthetic-aperture-radar backscatter of the surface of Venus from
NASA's Magellan mission: full-resolution (75 m/pixel) Mosaic Image Data
Records, data set `MGN-V-RDRS-5-MIDR-FULL-RES-V1.0`, read from the anonymous
PDS/USGS Astrogeology bucket `asc-pds-magellan`.

## Material

- Natural record: one F-MIDR framelet file `ffNN.img` with its detached PDS3
  label `ffNN.lbl`. Each F-MIDR is a 7168 x 8192 mosaic stored as 56
  separately labelled 1024 x 1024 framelets (7 rows x 8 columns).
- Value: `DN = INT((MIN(MAX(RV,-20),30) + 20) * 5) + 1`, where RV is radar
  cross section per unit area divided by the Muhleman law, in dB (0.2 dB per
  DN, DN 1..251). DN 0 is the only special value, declared in the VICAR header
  as `MISSING DATA`. The recipe keeps DN 0 in place and never converts to dB.
- Scope: six complete F-MIDRs from six MIDR volumes, all 56 framelets each,
  giving 336 samples of 1,048,576 values (352,321,536 bytes):

  | volume | MIDR | approx. centre | terrain (indicative) |
  |---|---|---|---|
  | mg_0006 | F-MIDR.25S003 | 25S 3E | Alpha Regio tessera |
  | mg_0007 | F-MIDR.65N018 | 65N 18E | Ishtar Terra highlands |
  | mg_0013 | F-MIDR.35S130 | 35S 130E | Artemis region |
  | mg_0015 | F-MIDR.05S098 | 5S 98E | Aphrodite Terra |
  | mg_0025 | F-MIDR.10N188 | 10N 188E | Sapas Mons area |
  | mg_0046 | F-MIDR.20N286 | 20N 286E | Beta Regio / Devana Chasma |

## Selection (`discover.sh`)

The bucket holds 765 F-MIDR directories (`f*`) on MIDR volumes
mg_0001-mg_0127. C1/C2/C3 compressed-resolution MIDRs, P-MIDRs, the FMAP
volumes mg_11xx-14xx, the GxDR volumes mg_3001/3002 and `edr/` are out of
scope. A MIDR is eligible when all of the following hold:

- its name occurs on only one volume (no re-released duplicate tiles);
- it is not on mg_0001, which uses an older one-record VICAR header;
- by its own published `HIST.TAB`, its DN-0 fraction is below 0.2 % and its
  maximum DN is at most 251.

137 MIDRs are eligible. Six were picked, one per volume, to spread latitude
and terrain. `SURVEY=1 bash discover.sh` re-fetches every listing and
histogram (metadata only), rewrites `histogram_survey.tsv`, and checks that
the regenerated plan matches `sources.tsv` byte for byte.

## Run

    bash staging/nasa_pds_magellan_fmidr_sar_u8/download.sh   # 685 files, 354,780,608 bytes
    bash staging/nasa_pds_magellan_fmidr_sar_u8/build.sh
    bash staging/nasa_pds_magellan_fmidr_sar_u8/verify.sh

`download.sh` checks the size and MD5 of every file; the MD5 is the S3
single-part ETag. It then schema-validates every label and VICAR header. It
resumes `.part` files on rerun.

## Decoding and checks

The label pointer `^IMAGE = ("FFNN.IMG",3)` names the file in upper case;
the bucket key is lower case. The parser maps the case explicitly and checks
the framelet number. It skips the 2048-byte VICAR2 header and keeps exactly
1,048,576 bytes. Build and verify check the following:

- the label identity and geometry;
- the VICAR keywords: `PRODUCT`, `SUBFRAME`, `SUBF_ROW`, `SUBF_COL`,
  `SPDN_1=0`, `LOW_REP=-20`, `HI_REP=30`, `NBB=NLB=0`;
- that each MIDR's 56 framelet histograms sum exactly to its `HIST.TAB`.

Drop rule, applied identically in both scripts: a framelet is dropped when
more than half of its pixels are DN 0. With this selection nothing is
dropped, because the largest MIDR DN-0 count is 111,758 pixels. Verify
re-derives every retained framelet from the downloads and compares bytes,
statistics and the pinned aggregate hash. It also rejects constant
framelets, framelets with fewer than 16 distinct DNs, DN > 251, and duplicate
samples.

## Realized output (build of 2026-10-05)

- 336 samples, 352,321,536 bytes. No framelet was dropped; the largest DN-0
  count in any one framelet is 78,549 pixels (7.5 %).
- All six MIDRs' framelet histograms equal their HIST.TAB exactly.
- Per-framelet distinct DNs range from 117 to 250, and mean DN from 97.1 to
  166.2. DN 0 is 0.063 % of all retained pixels.
- zlib level 6 reaches only about 0.74-0.78 of the original size on sampled
  framelets, which reflects the SAR speckle texture.
- The aggregate SHA-256 is `811298b0...789180f`, pinned in
  `expected_output.json`.

## Known caveats

- Two VICAR header generations exist. Volumes up to about mg_0035 write
  `IMAGE='RADAR CROSS SECTION POWER' HI_DN=250`; later volumes write
  `'NORMALIZED RADAR CROSS SECTION' HI_DN=251`. Both run the same processing
  chain (LOGMOS, SFASTMOS, COPY), and their PDS labels state the same DN law
  with the Muhleman constant 0.0118. The early MIDRs also contain DN 251. Five
  of the selected MIDRs use the early header and one (mg_0046) the later one.
- Some MIDRs are seam-corrected (`SEAM='CORRECTED'`) and others are not; this
  is recorded per sample in the index.
- License: the NASA SMD open-data policy, the same evidence as the accepted
  PDS recipes. The policy page is proxy-blocked here and is not fetched.
