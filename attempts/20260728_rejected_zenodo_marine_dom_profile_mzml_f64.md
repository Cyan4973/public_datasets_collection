# Rejected Attempt: `zenodo_marine_dom_profile_mzml_f64`

- Date: 2026-07-28
- Status: `rejected`
- Source: Zenodo record `10054333`, “2D-LC-MS/MS based non-targeted metabolomics of marine DOM (.mzML files)”
- License: CC BY 4.0
- Evidence: `.data/logs/zenodo_marine_dom_profile_mzml_f64/`, `.data/downloads/zenodo_marine_dom_profile_mzml_f64/zenodo_record.json`, and `reports/64bit_mzml_development_20260728.md`

## Why it looked useful

The record is a coherent open LC-MS/MS study, distributes standard mzML rather
than proprietary vendor files, and contains 97 versioned mzML payloads. A real
profile spectrum with explicit 64-bit binary arrays would be a novel natural
sample geometry for the 64-bit corpus.

## Realized result

The user-run downloader selected two deterministic study files:

- `2D_Frac_10-12a.mzML` (`38,731,932` bytes)
- `2D_Frac_10-12a_NEG.mzML` (`42,336,595` bytes)

Both passed Zenodo MD5 validation and local XML validation. Inspection of every
spectrum and binary-array CV declaration found:

- positive-mode file: `4,151` spectra, all centroided
- negative-mode file: `5,594` spectra, all centroided
- every m/z array: explicitly float32 plus zlib
- every intensity array: explicitly float32 plus zlib
- median natural spectrum lengths: `63` and `24` values
- qualifying native-float64 profile arrays: `0`

The maximum observed centroid lengths reached 4,250 and 3,060 values, but the
median natural records remain far below floor and the stored representation is
still float32.

## Decision

Reject this dataset ID for the 64-bit target. Widening float32 arrays to float64
would be a gratuitous width mirror, and concatenating centroid spectra would
violate natural record boundaries.

## Retry condition

Do not retry Zenodo record `10054333` as a 64-bit source. A successor must pin a
different permissively licensed source whose mzML metadata explicitly declares
profile spectra (`MS:1000128`) and native 64-bit arrays (`MS:1000523`), with a
median of at least 1,000 values per natural spectrum.
