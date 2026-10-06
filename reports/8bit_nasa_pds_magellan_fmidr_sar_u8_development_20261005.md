# Magellan Venus F-MIDR SAR framelet uint8 development

## Outcome

Accepted `nasa_pds_magellan_fmidr_sar_u8`. The recipe collects native 8-bit Magellan S-band synthetic-aperture-radar backscatter from full-resolution Venus Mosaic Image Data Records (F-MIDRs, data set `MGN-V-RDRS-5-MIDR-FULL-RES-V1.0`).

This is the second planetary SAR family in the local corpus. `nasa_pds_cassini_radar_bidr_sigma0_u8`, accepted the same day, is Ku-band Titan sigma0. The two differ in:

- mission and instrument;
- target body;
- radar band (S band at 12.6 cm here, Ku band for Cassini);
- resolution (75 m/pixel here, about 351 m/pixel for Cassini);
- DN lattice (0.2 dB per DN, Muhleman-normalized, here; 0.1 dB per DN, incidence-angle corrected, for Cassini).

The two must stay separate families. Novelty kind: `new_source`. It is not `new_modality`, because 8-bit planetary SAR dB imagery now exists locally.

## Source and rights

- **Source:** the anonymous USGS Astrogeology / PDS Imaging Node bucket `asc-pds-magellan` (us-west-2), which holds the PDS3 MIDR CD-ROM volumes mg_0001–mg_0127.
- **Download:** 685 files, 354,780,608 bytes:
  - 336 framelet `.img` files and their 336 detached `.lbl` labels;
  - six `hist.tab` / `hist.lbl` pairs;
  - the F-MIDR data-set description label.
- **Pinning:** `sources.tsv` pins every file's byte size and S3 single-part ETag (MD5). Its own SHA-256 (`9b8fb2e78c08e043774348d9141ba76762f6aa8ef16770de65ec85c89f00d6a0`) is pinned in `download.sh` and in the parser.
- **Discovery:** `discover.sh` regenerates the plan from metadata alone (S3 listings plus 1 KiB HIST.TAB files). The regenerated plan is byte-identical to `sources.tsv`.
- **Rights:** NASA SMD Scientific Information Policy (SPD-41a), cited the same way as the accepted `nasa_pds_cassini_vims_qube_i16`, `nasa_pds_mastcamz_raw_i16`, `nasa_pds_cassini_radar_bidr_sigma0_u8`, `nasa_heasarc_nicer_pi_i16` and `nasa_heasarc_nicer_detector_u8`.
  - Magellan was a NASA/JPL mission, and the 1990–1993 archive products are distributed anonymously by the official PDS node.
  - **Limitation:** the policy page and the SPD-41a PDFs are unreachable through this environment's proxy, so the text was not re-read; acceptance rests on that precedent.
- **Safety:** no credentials and no personal data. Operator IDs in the VICAR headers and contact names in `aareadme.txt` stay in the downloads and never reach samples or index rows.

## Shape and conversion

Each natural record is one F-MIDR framelet file `ffNN.img` with its detached PDS3 label `ffNN.lbl`. The volume `aareadme.txt` states: "Each framelet is stored in a separate file. A framelet is 1024 lines by 1024 samples, with one byte per sample." Each MIDR is a 7168x8192 mosaic stored as 56 such files (7 rows x 8 columns).

The label declares FILE_RECORDS=1026, a two-record VICAR2 header, `^IMAGE = ("FFNN.IMG",3)`, and an IMAGE object of UNSIGNED_INTEGER with 8 sample bits. Its NOTE gives the DN law `DN = INT((MIN(MAX(RV,-20),30) + 20) * 5) + 1`, where RV is radar cross section per unit area divided by the Muhleman law (constant 0.0118), in dB.

The parser:

- maps the upper-case pointer name to the bucket's lower-case key;
- skips 2048 bytes, cross-checked against VICAR LBLSIZE=2048 with NBB=NLB=0;
- copies 1,048,576 bytes unchanged, line-major as stored.

There is no rescaling, no dB conversion and no remapping. DN 0 (VICAR `SPDN_1=0 'MISSING DATA'`) stays in place.

### Selection

- Population: 765 F-MIDR directories.
- Eligibility, using each MIDR's own HIST.TAB: the name appears on only one volume, the volume is not mg_0001 (older one-record header), the DN-0 fraction is below 0.2 %, and the maximum DN is at most 251.
- Result: 137 eligible MIDRs across 47 volumes.
- Six were chosen, one per volume, for latitude and terrain spread:
  - mg_0006 f25s003: Alpha Regio;
  - mg_0007 f65n018: Ishtar Terra;
  - mg_0013 f35s130: Artemis;
  - mg_0015 f05s098: Aphrodite Terra;
  - mg_0025 f10n188: Sapas Mons;
  - mg_0046 f20n286: Beta Regio.
- Known bias: fully covered mosaics were preferred on purpose, so edge framelets with heavy zero fill are under-represented.

### Drop rule

Build and verify apply the same rule: drop a framelet if more than 524,288 of its pixels are DN 0. For this selection it drops nothing.

### Header generations

Five MIDRs use the 1991 VICAR wording `RADAR CROSS SECTION POWER, HI_DN=250`. mg_0046 uses `NORMALIZED RADAR CROSS SECTION, HI_DN=251`. All six labels carry the identical DN law and Muhleman-constant note, and all six use the same LOGMOS→SFASTMOS→COPY chain. The early MIDRs also contain DN 251, so their HI_DN=250 is inaccurate metadata, not a different scale.

Seam correction differs between MIDRs (3 corrected, 3 uncorrected) and is recorded per sample in the index.

## Accepted output

- F-MIDRs: 6, on 6 volumes
- Framelets inspected: 336
- Framelets dropped: 0
- Primary samples: 336
- Primary values / bytes: 352,321,536
- Sample shape: 1024 x 1024 uint8 (1,048,576 values each; median = minimum = maximum)
- DN 0 (missing data): 221,906 pixels (0.063 %); the largest count in one framelet is 78,549
- Distinct DNs per framelet: 117–250
- Mean DN per framelet: 97.1–166.2
- Every MIDR's summed framelet histograms equal its published HIST.TAB
- Aggregate SHA-256: `811298b0c29c03f7a791b53f427398f0a891af8c06ce8ac8fe461ae9d789180f`

## Judge checks

- **Gate:** `python3 tools/autocollect/gate.py staging/nasa_pds_magellan_fmidr_sar_u8` passed with no warnings.
- **Verify:** I re-ran `verify.sh` myself (selftest plus a full independent re-derivation). It reproduced the pinned aggregate hash.
- **Local-only build:** build.sh and verify.sh contain no network calls and no credentials.
- **Plan pin:** `.data/discovery/.../sources.generated.tsv` is byte-identical to `sources.tsv`.
- **Selection survey:** 765 HIST.TABs surveyed and 137 eligible across 47 volumes, exactly as claimed.
- **Bytes, all 336 samples (stdlib):**
  - global DN range 0–251, 252 distinct values;
  - quantiles p1=80, p50=120, p99=189;
  - no pile-up at the clip limits: DN 1 has 1,446 pixels and DN 251 has 316.
- **Bytes, 12 random framelets:**
  - mean neighbour difference 5.9–11.9, versus 12.2–25.6 for random pixel pairs, so the image has genuine 2-D spatial structure on 1024-pixel lines;
  - zlib level 6 ratio 0.696–0.820;
  - longest constant run 4–7 pixels.
- **Payload start:** samples begin with pixel values, not header text.
- **Zero-heaviest framelet:** its DN-0 pixels form a diagonal orbit-gap stripe, with no fully zero rows.
- **Duplicates:** every sample SHA-256 is unique. The six MIDRs cover disjoint latitude bands, so there are no geographic duplicates.
- **Homogeneity:** I read all six labels' NOTE fields and VICAR headers and confirmed the identical DN law and Muhleman constant and the same processing chain.
- **Novelty:** `novelty.py --url https://asc-pds-magellan.s3.us-west-2.amazonaws.com/ --url asc-pds-magellan --terms magellan venus midr fmidr framelet muhleman MGN-V-RDRS` matched only this candidate and the stale unregistered draft `staging/nasa_pds_magellan_sar_i16`. The registry shows `nasa_pds_cassini_radar_bidr_sigma0_u8` as accepted, so this recipe is labelled `new_source`, not the builder's "new source and modality".
- **Rights:** I tried to fetch the NASA SMD policy (science.nasa.gov page and SPD-41a PDFs) and every attempt failed at the proxy. Rights rest on the five accepted precedents citing the same policy for NASA mission data.
