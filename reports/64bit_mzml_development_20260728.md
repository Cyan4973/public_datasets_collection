# 64-bit Profile mzML Development — 2026-07-28

Goal: develop the highest-priority remaining 64-bit domain-diversity candidate:
native double-precision profile mass spectra.

No external dataset payload was downloaded by the agent.

## Selected Source

The staged recipe targets Zenodo record `10054333`, titled “2D-LC-MS/MS based
non-targeted metabolomics of marine DOM (.mzML files).” This is preferable to a
generic ProteomeXchange search because it is a fixed versioned record dedicated
to mzML files and describes one coherent chemical-instrument study.

The user-run downloader reads `https://zenodo.org/api/records/10054333` before
payload acquisition and requires:

- an allowed permissive license identifier
- actual `.mzML` or `.mzML.gz` files
- positive declared sizes below the per-file cap
- a deterministic sorted selection below the total byte cap
- agreement with Zenodo's declared MD5 checksum after download

The exact realized license, file inventory, and content remain promotion gates.

## Decoder Policy

The local decoder keeps only arrays whose mzML CV metadata explicitly declares:

- profile spectrum: `MS:1000128`
- 64-bit float: `MS:1000523`
- m/z array: `MS:1000514`, or intensity array: `MS:1000515`
- no compression or zlib compression supported by the standard-library path

It rejects or excludes centroid spectra, float32 widening, Numpress payloads,
malformed base64/zlib data, non-finite values, constant arrays, and natural
spectra below 1,000 values. Each spectrum array remains a physical sample; the
recipe does not concatenate spectra to clear the floor.

At most the first 4,096 qualifying spectra per source file are retained, and
total primary output is capped at 900 MB.

## User Runbook

```bash
bash staging/zenodo_marine_dom_profile_mzml_f64/download.sh
bash staging/zenodo_marine_dom_profile_mzml_f64/build.sh
bash staging/zenodo_marine_dom_profile_mzml_f64/verify.sh
```

The first user-run download is expected to answer the remaining empirical
questions: record license, payload sizes, profile/centroid mode, actual binary
precision, compression, and spectrum-length distribution.

## Realized Result: Rejected

The user-run acquisition confirmed CC BY 4.0 metadata and downloaded two
checksum-verified mzML files totaling `81,068,527` bytes. The source is a valid,
coherent mass-spectrometry dataset, but it does not contain the target material.

Full local CV inspection found:

| file | spectra | mode | m/z storage | intensity storage | median points | maximum points |
|---|---:|---|---|---|---:|---:|
| `2D_Frac_10-12a.mzML` | 4,151 | centroid | float32 + zlib | float32 + zlib | 63 | 4,250 |
| `2D_Frac_10-12a_NEG.mzML` | 5,594 | centroid | float32 + zlib | float32 + zlib | 24 | 3,060 |

No binary array was both profile-mode and native float64. The dataset is
therefore rejected for the 64-bit corpus. Float32 widening and cross-spectrum
concatenation are both prohibited repair paths.

The negative result is registered as
`attempts/20260728_rejected_zenodo_marine_dom_profile_mzml_f64.md`. A future
successor must use a different source explicitly carrying `MS:1000128` profile
spectra and `MS:1000523` 64-bit arrays with median natural length at least 1,000.
