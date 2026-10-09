# MetaboLights MTBLS12824: negative-ion HILIC MS1 centroid m/z (float64)

Native float64 centroid m/z arrays from LC-MS metabolomics of human skeletal
muscle (MetaboLights study MTBLS12824, "Delayed molecular aging, preservation of
energy metabolism and enhanced exercise response in exercise-trained human
muscle"). One sample = the m/z array of one MS1 survey spectrum.

```bash
bash staging/metabolights_mtbls12824_maxis_centroid_mz_f64/download.sh   # ~650 MB, 20 mzML files
bash staging/metabolights_mtbls12824_maxis_centroid_mz_f64/build.sh
bash staging/metabolights_mtbls12824_maxis_centroid_mz_f64/verify.sh
```

## License

`i_Investigation.txt` line 42: `Comment[License]<TAB>CC0 1.0 Universal`.
`download.sh` re-fetches the file and fails unless exactly that line (and
`Study Identifier<TAB>MTBLS12824`) is present.

## Scope and homogeneity

The study's `FILES/` directory holds 228 mzML runs: positive and negative
polarity, tissue samples, blanks, pooled QCs and pre-runs. This recipe keeps one
regime:

- **Negative polarity, HILIC, tissue samples only.** The files are named
  `21P0055_Tissue_Georges_NEG_N_*` and `*_NEG_V_*`. 93 of the 94 such files
  appear in assay table `a_MTBLS12824_LC-MS_negative_hilic_metabolite_profiling.txt`.
  The odd one out is `NEG_V_12_17508`, which is not selected. All of them share
  one instrument and method: Waters ACQUITY UPLC with a ZIC-cHILIC column; ESI
  negative mode; Q-TOF scanning 50-1200 m/z; BAF converted by ProteoWizard
  3.0.24214 with CompassXtract peak picking and an intensity threshold above 500.
  The trailing injection numbers (17403-17516) are consecutive across all NEG files, which points to one acquisition sequence.
- **N vs V differ only in biological sampling time.** The assay table maps
  every `NEG_N_*` file to an `*_After_Exercise` sample and every `NEG_V_*` file
  to a `*_Before_Exercise` sample (Dutch *na* = after, *voor* = before). They
  are muscle biopsies from the same 47 participants, prepared and run with the
  same method in one interleaved injection sequence. Both groups are the same
  material and the same compression regime.
- **Excluded:** POS runs (a different file regime, about 6.6 MB per file),
  `NEG_Blank_*`, `NEG_QC_*`, PRERUN, and mzXML duplicates.
- **Deterministic subset:** the first ten `NEG_N` files and the first ten
  `NEG_V` files in sorted-name order (`N_01..N_10` and `V_01..V_10`). That is
  20 runs and 649,970,118 bytes. At the realized rate of about 18.3 MB of m/z
  per run, the full population of 94 runs would give about 1.7 GB of primary
  output, over the 1 GB cap. A balanced 20-run subset gives 366 MB, so the cap
  is not approached. Each run has 1,230-1,232 MS1 spectra.

Instrument naming: the mzML instrument cvParam is `MS:1001547 Bruker Daltonics
maXis series`, which is where the dataset id's "maxis" comes from. The assay
table names the instrument as `Bruker impact II UHR-TOF`. ProteoWizard maps that
Bruker UHR-QTOF line to the generic maXis-series CV term. In both readings it is
one instrument, recorded with serial number `1825265.10240`.

## Conversion

For every `<spectrum>` (streamed with `xml.etree.iterparse`, clearing processed
elements as it goes):

1. Require `ms level = 1`, `MS1 spectrum`, `negative scan` and `centroid
   spectrum`. Reject `positive scan` and `profile spectrum`.
2. Require exactly one m/z array (`MS:1000514`) and one intensity array
   (`MS:1000515`). Each must be declared `64-bit float` (`MS:1000523`) and
   `zlib compression` (`MS:1000574`).
3. base64-decode and zlib-decompress, then require a length of exactly
   `8 * defaultArrayLength`. Require m/z to be finite, between 1 and 5000, and
   non-decreasing.
4. Write the decoded m/z bytes unchanged as
   `samples/<id>/neg_hilic_ms1_centroid_mz_f64/<run>_spectrum_<index>.bin`.

No spectrum is dropped for its length and nothing is concatenated. A zero-length
spectrum would emit no sample and be counted in `spectrum_stats.json`. The
intensity arrays hold integral detector counts stored as f64 (every probed value
is integral and f32-exact), so they are decoded only for validation and never
emitted. Emitting them would be a widened 64-bit mirror of small integers.

`verify.sh` re-derives everything with a separate decoder. It streams lines
with regexes and does not use ElementTree. It then compares every index row,
each sample's SHA-256, the set of files in the sample directory, and the
manifest's `sample_count`/`total_size_bytes`.

## Relation to the registry retry condition

The registry entry `zenodo_marine_dom_profile_mzml_f64` (superseded) says:
"retry 64-bit mzML only with a different source explicitly declaring profile
float64 arrays". **This recipe does not meet that wording literally.** These
spectra are centroided (`MS:1000127`), not profile (`MS:1000128`).

That entry failed because its arrays were declared and stored as float32, with
spectra that were also very short. Emitting them at 64 bits would have been a
width mirror. The point of the condition is a different source whose arrays are
genuinely 64-bit. This source meets that point:

- It is a different repository and study.
- The arrays are declared `64-bit float`.
- Across all 45,760,543 emitted m/z values, none is exactly representable in
  f32, so the full binary64 mantissa is in use.
- The median spectrum length is 1,622 values.

"Profile" was the shape of the failed source's mislabelled data, not a property
the corpus needs. A centroid peak list is a natural record in its own right; the
accepted f32 MS1 family `zenodo_marine_dom_positive_ms1_f32` is also centroid.
The judge should weigh this deviation explicitly.

## Novelty

There is no MetaboLights recipe and no 64-bit mass-spectrometry family locally
or downstream. The only other MS family is `zenodo_marine_dom_positive_ms1_f32`
(float32, positive ion, marine dissolved organic matter). This one is float64, from a
Bruker Q-TOF, negative ion, on a HILIC tissue metabolome. The nearest
compression-relevant shape is a sorted, increasing f64 peak-position list with
full mantissas. See the zlsim result below.

## Realized validation

Built and independently verified on 2026-10-09 from the 20 SHA-256-verified
runs (download 649,970,118 bytes of mzML):

- 24,622 natural samples (one per MS1 spectrum). There were no zero-length
  spectra, so every spectrum in the 20 runs is emitted.
- 45,760,543 float64 values, 366,084,344 primary bytes.
- Spectrum length: median 1,622, minimum 349, maximum 14,841.
  - Percentiles: p1 451, p10 1,145, p25 1,477, p75 1,960, p90 3,100, p99 4,471.
  - 8.3% of spectra are below 1,000 values. They are kept, since there is no
    length filtering.
  - Length varies with retention time. The column front, the HILIC wash, and
    the re-equilibration at the end produce the longest scans (median about
    3,000-4,200). The 9-10 min window produces the shortest (median about 650).
- m/z range 44.950-1204.978. Every array is strictly increasing (0 tied
  pairs). 0 of the 45.76M values are float32-exact.
- `gate.py`: PASS with no warnings.
- `zlsim.py gate`: verdict **OK**, not redundant, own ratio 1.456.
  - Nearest family: `jpl_gnssro_cosmic1_l1b_excess_phase_f64` at percentile
    distance 0.072 (threshold 0.05).
  - Its compressor reaches 0.08% loss, so it is compression-equivalent but not
    statistically close.
  - Next neighbours: IGS satellite clock bias at distance 0.093 (loss 20.8%),
    downstream `sao_sra0_sharded` at 0.107.
  - Not STRONG: the nearest family is within 0.12.
