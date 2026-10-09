# 64-bit MetaboLights MTBLS12824 negative-ion HILIC MS1 centroid m/z development

## Outcome

Accepted `metabolights_mtbls12824_maxis_centroid_mz_f64`. It holds native IEEE-754 float64 centroid m/z arrays, one sample per MS1 survey spectrum, from negative-ion HILIC LC-MS runs of human skeletal-muscle extracts in EMBL-EBI MetaboLights study MTBLS12824.

This is the first 64-bit mass-spectrometry family, locally or downstream. The local accepted `zenodo_marine_dom_positive_ms1_f32` family covers the same modality (MS1 centroid m/z), but it is float32, positive-ion, marine DOM, and from a different archive. Novelty is therefore `new_content_same_modality`.

The superseded `zenodo_marine_dom_profile_mzml_f64` entry has a retry condition that asks for "profile float64" arrays. These spectra are centroid (MS:1000127). The deviation is accepted deliberately because the condition's substance is met:
- a different permissively licensed source;
- arrays declared `64-bit float` and genuinely using the full binary64 mantissa;
- a natural-record median of at least 1,000 values.

## Source and rights

- Source: `https://ftp.ebi.ac.uk/pub/databases/metabolights/studies/public/MTBLS12824/`
- Study: "Delayed molecular aging, preservation of energy metabolism and enhanced exercise response in exercise-trained human muscle". Released 2026-04-09, revision 1.
- License: CC0 1.0 Universal. `i_Investigation.txt` line 42 reads `Comment[License]<TAB>CC0 1.0 Universal`. `download.sh` re-fetches the file on every run and fails unless that exact line and `Study Identifier<TAB>MTBLS12824` are present.
- Pinning: 20 mzML files, 649,970,118 bytes. Per-file size and SHA-256 are in `scripts/runs.tsv` and are cross-checked against upstream `HASHES/data_sha256.json`.
- Safety: the source is de-identified human biopsies collected under ethics approval and informed consent (NCT03666013). Only m/z peak positions are emitted: no sample names, phenotypes or intensities.

## Shape and conversion

**Regime.** The 94 `21P0055_Tissue_Georges_NEG_[NV]_*` runs are the Bruker negative-HILIC assay:
- Waters ACQUITY UPLC with a ZIC-cHILIC column, ESI negative, 50–1200 m/z.
- One instrument, serial `1825265.10240`.
- Converted by ProteoWizard 3.0.24214 with CompassXtract peak picking and an absolute intensity threshold above 500.
- `NEG_N` runs are after-exercise biopsies and `NEG_V` runs are before-exercise biopsies of the same participants, in one injection sequence (17403–17516).

**Excluded:** POS runs, blanks, pooled QCs, PRERUN, and the Thermo Q Exactive mzXML lipid assays.

**Selection:** the first ten N and first ten V runs in sorted-name order. These are paired before/after biopsies for participants ELMIH001–ELMIH021.

**Decoding.** Each `<spectrum>` must be:
- ms level 1, MS1 spectrum, negative scan and centroid;
- carrying exactly one m/z array and one intensity array, both declared `64-bit float` and `zlib`.

Each m/z array is base64-decoded and zlib-decompressed. Its length must equal `8*defaultArrayLength`, and its values must be finite, within 1–5000 and non-decreasing. The bytes are then written unchanged as little-endian f64. There is no length filter and no concatenation.

**Intensities** are integral detector counts stored as f64, and all of them are f32-exact. They are decoded only for validation and dropped, since emitting them would be a widened mirror.

**Verification.** `verify.sh` re-decodes the runs with an independent line-streaming regex decoder and compares every index row, per-sample SHA-256, the sample directory listing, and the manifest totals.

## Accepted output

- Runs: 20, with 1,230–1,232 spectra each and 0 empty spectra
- Primary samples: 24,622
- Primary values: 45,760,543
- Primary bytes: 366,084,344
- Spectrum length (values per sample):
  - median 1,622, minimum 349, maximum 14,841
  - p10 about 1,145, p90 about 3,100
  - 8.3% of spectra are below 1,000 values; length tracks retention time
- m/z range: 44.950459922321194 to 1204.978454899154, strictly increasing within every spectrum (0 ties)
- f32-exact values: 0 of 45,760,543
- Aggregate SHA-256 of all sample bytes in index order: `f1c95fc05053c134f2052cf35f962ad80b55f2a3a180df33072420b71db7861e`
- Breadth (zlsim, driver-measured): OK. The nearest family is `jpl_gnssro_cosmic1_l1b_excess_phase_f64` at distance 0.0719 (compression loss 0.08%, so not statistically close). The next is IGS clock bias at 0.093.

## Judge checks

- **Gate:** `tools/autocollect/gate.py` PASS with no warnings.
- **verify.sh:** I re-ran it; exit 0, reproducing the totals above. The decoder `selftest` also passes.
- **Third decoder:** my own whole-file regex decoder (stdlib base64/zlib/struct) reproduced all 1,230 spectra of `NEG_V_07_17413` byte for byte.
- **Value precision:** in two pooled samples (5,424 values), no value is exact at 3–9 decimals, trailing mantissa zeros are geometric, and all 256 low-byte values occur with max share 0.7%. These are full-precision computed doubles.
- **Duplicates:** no duplicate-SHA spectra. Run N_03 has 2,207,531 distinct values out of 2,207,537. Consecutive scans share no exact values and about 31% of peaks within 5 ppm, which is natural chromatographic carryover rather than near-duplication.
- **Intensity claim:** all 2,276,724 intensities in V_07 are integral and f32-exact; the 7 values above 2^24 are even.
- **Homogeneity:** the headers of all 20 runs carry an identical serial number, CV instrument term, software versions and processing methods. I fetched the four assay tables and confirmed that all 20 runs map to the negative-HILIC Bruker assay with the N→After and V→Before pairing. The other negative assays are Thermo mzXML lipid runs and are correctly excluded.
- **Rights:** the license line is present in the downloaded and live `i_Investigation.txt`. No credentials in any script.
- **Novelty:** `novelty.py` found no MetaboLights or 64-bit MS recipe, and the type/instrument/archive keys match nothing. Downstream 64-bit lists contain no mass spectrometry (`msd_*` is the Million Song Dataset).
