# MetaboLights MTBLS12824 Bruker maXis UHR-QTOF LC-MS Negative-Mode Tissue Runs: Native Float64 Centroid m/z Arrays (mzML)

- Candidate id: `metabolights_mtbls12824_maxis_centroid_mz_f64`
- Width: float64
- Quantity: Calibrated mass-to-charge (m/z, Th) of the centroided peaks in each MS1 scan of an LC-MS run. Read from mzML binaryDataArray 'm/z array' (MS:1000514), declared '64-bit float' (MS:1000523) plus 'zlib compression'. Only the m/z arrays are primary. The intensity arrays are integer counts stored as f64 (all integral and f32-exact), so they must be dropped or kept auxiliary.
- Source: https://ftp.ebi.ac.uk/pub/databases/metabolights/studies/public/MTBLS12824/
- Resources: https://ftp.ebi.ac.uk/pub/databases/metabolights/studies/public/MTBLS12824/FILES/, https://ftp.ebi.ac.uk/pub/databases/metabolights/studies/public/MTBLS12824/FILES/21P0055_Tissue_Georges_NEG_V_01_17495.mzML, https://ftp.ebi.ac.uk/pub/databases/metabolights/studies/public/MTBLS12824/i_Investigation.txt
- License: CC0-1.0
- License evidence: https://ftp.ebi.ac.uk/pub/databases/metabolights/studies/public/MTBLS12824/i_Investigation.txt
- License quote: Comment[License] CC0 1.0 Universal
- Natural record: One LC-MS acquisition (one mzML run file, about 1,232 MS1 scans) per sample, with scans in acquisition order and per-scan offsets as an auxiliary series. Fallback if the judge insists on scan-level records: one sample per scan's m/z array. The median scan length is about 2,500 values, so either choice clears the 1,000-value median floor.
- Estimated samples: 20
- Estimated primary values: 62,000,000
- Estimated download bytes: 640,000,000
- Estimated primary bytes: 495,000,000
- Decode path: Stdlib only. Parse the mzML XML with re or xml.etree iterparse. For each <spectrum>, take the binaryDataArray carrying the 'm/z array' cvParam, base64.b64decode then zlib.decompress, then struct.unpack('<Nd'). Check that the decoded length equals defaultArrayLength and that the declared cvParams are 64-bit float, centroid spectrum and MS1. Verified on range-fetched heads: 16-17 complete spectra decoded, with 0 of 2,513 m/z values exactly representable in f32.
- Novelty kind: new_quantity
- Measurement type: mass_spectrum_peak_mz
- Instrument line: bruker_maxis_uhr_qtof_lcms
- Archive collection: ebi_metabolights
- Novelty evidence: novelty.py --url on MTBLS12824 matches only the same EBI host (Pfam, EMPIAR), with no MetaboLights recipe. The only mass-spec family is zenodo_marine_dom_positive_ms1_f32 (32-bit, float32 arrays). The registry entry zenodo_marine_dom_profile_mzml_f64 was rejected because its arrays were float32 with medians of 63/24 values. Its retry condition asks for a different source with native 64-bit arrays and a median of at least 1,000 values per spectrum, and this source meets both. Nothing in the 64-bit local or downstream lists covers mass spectrometry. A sorted-within-scan peak-position stream with full 52-bit mantissas has a different shape from the existing f64 families.
- Homogeneity: Restrict to one regime: the NEG-polarity tissue sample runs (patterns *_NEG_N_* and *_NEG_V_*, 94 files of about 30-33 MB each). All come from one instrument (Bruker maXis, micrOTOFcontrol, CompassXtract peak picking, ProteoWizard conversion), one polarity, one scan window and one study batch. Exclude POS (a different file regime, about 6.6 MB per file), blanks, QCs and PRERUN. Take a deterministic subset of about 20 runs (sorted by name) for about 500 MB of primary output.
- Risks: (1) The retry condition's wording says 'profile' (MS:1000128), and these spectra are centroided. The substantive conditions (native 64-bit arrays, a median of at least 1,000 values, a different source) are met, and the builder or judge should state this explicitly. (2) Natural-record choice: run-level samples could be read as concatenating scans. Scan-level samples are a valid fallback (median about 2,500 values) but mean many files. (3) Older MetaboLights studies carry 'EMBL-EBI Terms of Use' (cf. the EMDB block), but this study's investigation file says CC0 1.0 Universal. Pin that file in download.sh and check the license line. (4) About 25% of each run file is f64 intensity bytes that get discarded.
- Probe evidence: The FILES directory listing is live: 228 mzML and 330 mzXML. A range GET of 0-400000 on NEG_Blank_01_17403.mzML and 0-600000 on NEG_V_01_17495.mzML returned 206. In both, cvParams show 64-bit float plus zlib for m/z and intensity, centroid spectrum, MS1, negative scan, and the instrument 'Bruker Daltonics maXis series'. spectrumList count is 1232, and defaultArrayLength runs from 2,440 to 3,573 (median 2,505) in the sample run. Decoded m/z: 0 f32-exact, all distinct. Decoded intensity: all integral.

Proposed by the autocollect scout on 2026-10-08 (transcript `.data/pipeline/logs/scout_64bit/scout.20261008_231914.jsonl`).
