# CSIRO Parkes UWL/Medusa 8-bit search-mode filterbank development

## Outcome

Accepted `csiro_parkes_uwl_search_mode_u8`: native unsigned 8-bit detected radio power and cross-power from the Parkes 64 m telescope (Murriyang). The data were recorded with the Ultra-Wideband Low (UWL) receiver and the Medusa backend in PSRFITS SEARCH mode while tracking Proxima Centauri. They come from ATNF project P1018, 29 April to 4 May 2019.

This is the first radio-astronomy filterbank family in the corpus. The only related accepted family, `zenodo_crab_giant_pulse_sigmf_ci16`, holds raw complex baseband voltages. This recipe holds detected, requantized coherency products, the search-mode dynamic spectra used for pulsar and transient searches.

The recipe went through two documentation-only repairs:
1. The first corrected the per-channel σ and lag-1 figures and the resource size.
2. The second resolved the frequency lag-1 aliasing caused by Medusa's native 8-sample periodicity. It also re-described the zero codes in one BB plane as an unflagged backend dropout rather than RFI or clipping.

Neither repair changed the bytes.

## Source and rights

- **Source:** the CSIRO Data Access Portal, "Parkes observations for project P1018 semester 2019APRS".
  - Seven UWL collections are used: 39663, 39717, 39718, 39719, 39720, 39722 and 41486.
  - 66064 is empty and 41516 holds BPSR data from a different backend.
- **Access:** an anonymous DAP API, `/collections/<id>/data`, issues presigned `s3.data.csiro.au` links that expire after 48 h. download.sh refreshes them on every run.
- **Licence:** CC BY 4.0 (DAP licence 1121, rightsUri https://creativecommons.org/licenses/by/4.0/).
  - Every collection record and `/data` listing is accessLevel Public and dataRestricted FALSE, with no embargo.
  - Rights statement: "All Rights (including copyright) CSIRO 2019."
- **Attribution:** cite the seven collection DOIs, 10.25919/5ccc698a95721 through 10.25919/5d9516d17f6d0, for example Zic et al. (2019), 10.25919/5cd04712280ca.
- **Pinned files:** eight 12,273,488,640-byte `.sf` files. sources.tsv pins each file's DAP id, fileSize and log MD5, plus SHA-256 values for the header range, the row's auxiliary prefix and the full row.

## Shape and conversion

- **Selection:** the 50 ProxCen_S on-source observations are listed in each collection's `<id>.log`. 39 of them have all 16 files inside one collection.
  - Picks are eligible indices `round(i*38/7)` for i = 0..7, in time order.
  - Each pick uses file `_8`, the middle of the observation, and SUBINT row 112 of 224.
  - Calibrator, pulsar-check, reference and noise-diode scans are excluded.
- **Fetch:** two exact HTTP 206 ranges per file: bytes 0–25919 (headers) and one 54,792,232-byte SUBINT row.
- **Header validation:** every header must show:
  - FRONTEND UWL, BACKEND Medusa, OBS_MODE SEARCH
  - SRC_NAME ProxCen_S, TRK_MODE TRACK, CAL_MODE OFF
  - NBITS 8, SIGNINT 0, NPOL 4, POL_TYPE AABBCRCI
  - NCHAN 3328, NSBLK 4096, TBIN 128 µs, ZERO_OFF 127.5
- **Layout:** the DATA column offset (266,280 bytes) is computed from the TFORM widths and cross-checked against NAXIS1. The HDU layout must predict the DAP fileSize exactly.
- **Natural record:** one SUBINT row. Its DATA cell has TDIM (3328,4,4096), so bytes run `[time][pol][channel]` with channel fastest.
- **Split:** each row is split along the polarization axis into four series, each sample a row-major 4096 × 3328 uint8 plane.
  - `parkes_uwl_search_aa_u8` and `parkes_uwl_search_bb_u8` hold auto-power.
  - `parkes_uwl_search_cr_u8` and `parkes_uwl_search_ci_u8` hold the real and imaginary cross terms.
  - Bytes are copied verbatim.
- **Auxiliary columns:** DAT_FREQ, DAT_WTS, DAT_SCL and DAT_OFFS are validated but not applied and not emitted.

## Accepted output

- Rows: 8 (8 observations, 6 days, 7 collections)
- Primary samples: 32 (8 per series)
- Values per sample: 13,631,488 (4096 time samples × 3328 channels)
- Primary bytes: 436,207,616 (109,051,904 per series)
- Download: 438,545,216 bytes of exact ranges, about 1 MB of API JSON on top
- Aggregate SHA-256 over the raw per-sample digests, sorted by sample_path: `40fef49881f6b3188443e2e05f67e245d04c06daa2459cc67e9827db93d3ba25`
- Code statistics:
  - Plane means are 127.49–127.50 and σ is 15.8–15.9.
  - Entropy is 5.99–6.03 bits per byte.
  - Single planes compress 1.31× with zstd -19 and with xz -9.
  - AA/BB use 197–256 distinct codes; CR/CI use all 256.
- Documented features, kept verbatim:
  - Medusa's native 8-sample periodicity: spectra with t%8==0 have wider σ and higher adjacent-channel correlation.
  - One unflagged backend dropout in the BB plane of uwl_190503_135452: 6,505 zero codes at t = 0, 512, …, 3584 within 1344–2368 MHz.

## Judge checks

- **Gate:** `python3 tools/autocollect/gate.py staging/csiro_parkes_uwl_search_mode_u8` passes with no warnings.
- **Verify:** `bash staging/csiro_parkes_uwl_search_mode_u8/verify.sh` exits 0 with 32 samples verified slice by slice against the downloaded rows.
- **Download pins:** download.sh's SHA-256 equals the driver's recorded download_sha. Offline `check-header` and `check-row` with the current sources.tsv print "(pinned)" for all 8 row SHA-256 values.
- **Selection:** `discover.sh` with `PROBE_RANGES=0`, run against metadata I fetched fresh into /tmp, reproduces the 8 picks in sources.tsv exactly (50 observations, 39 eligible).
- **Digest:** I recomputed the aggregate digest from the index and it matches.
- **Rights:** I fetched the DAP collection record for 39720 and licence 1121 myself, plus fresh `/data` listings and collection records for all 7 collections. All are CC BY 4.0, Public and unrestricted. The scripts contain no credentials.
- **Novelty:** `novelty.py` with the DAP URL and the terms parkes, psrfits, pulsar, filterbank, medusa, csiro, "search mode", uwl, spectrogram and radio finds only the ci16 Crab baseband voltage capture locally and downstream.
- **Bytes**, from a stdlib scan of all 32 planes:
  - Per-plane statistics, 0/255 counts and the phase-resolved lag-1 table all match the README.
  - Skew is +0.40 for AA (auto-power) and about 0 for CR (cross term).
  - DAT_OFFS is about 1.2–1.4e6 for AA/BB and near zero for CR/CI, confirming the product labels.
  - Same-row AA–BB correlation is 0.05–0.09 with chance-level byte equality, so there are no near-duplicates.
  - The dropout's positions, zero counts, channel span and sub-band means match the documentation exactly.
  - zstd -19 and xz -9 ratios match.
