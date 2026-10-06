# CSIRO Parkes UWL/Medusa 8-bit search-mode filterbank rows (`csiro_parkes_uwl_search_mode_u8`)

Native **uint8** detected radio power and cross-power from the Parkes 64 m
telescope (Murriyang). The data were recorded with the Ultra-Wideband Low
(UWL) receiver and the Medusa backend in PSRFITS SEARCH mode while tracking
Proxima Centauri for ATNF project P1018 ("Wide-band radio monitoring of space
weather on Proxima Centauri", A. Zic et al.), 29 April to 4 May 2019.

## Material

- Instrument configuration (identical in all eight pinned files):
  - 3328 channels of 1 MHz each, 704–4032 MHz
  - 128 µs sampling, 4096 samples per SUBINT row (0.524 s)
  - 4 coherency products in `POL_TYPE = AABBCRCI`
  - `NBITS = 8`, `SIGNINT = 0`, `ZERO_OFF = 127.5`
- The natural record is one PSRFITS SUBINT row. Its `DATA` cell has
  `TDIM = (3328,4,4096)` (FITS order, channel fastest), i.e. bytes laid out
  `[time][pol][channel]`.
- Each row is split along its polarization axis into four homogeneous
  series. Each sample is one 4096 × 3328 time-by-channel uint8 plane, the
  raw requantized dynamic spectrum of one product:

  | series | product | meaning |
  |---|---|---|
  | `parkes_uwl_search_aa_u8` | AA | auto-power, receptor A |
  | `parkes_uwl_search_bb_u8` | BB | auto-power, receptor B |
  | `parkes_uwl_search_cr_u8` | CR | Re(A·B*) cross term (signed quantity around 127.5) |
  | `parkes_uwl_search_ci_u8` | CI | Im(A·B*) cross term (signed quantity around 127.5) |

- Bytes are copied verbatim. The per-channel `DAT_SCL`/`DAT_OFFS` calibration
  (`outval = dataval*scl + offs`), `DAT_WTS` and `DAT_FREQ` stay in the
  downloaded row as auxiliary metadata. They are validated but not applied
  and not emitted.

## Scope

DAP holds nine P1018 collections. 66064 is empty and 41516 is BPSR (a
different backend), which leaves seven UWL collections: 39663, 39717, 39718,
39719, 39720, 39722 and 41486. Each collection's `<id>.log` maps every file
to its scan directory. Only `ProxCen_S` (on-source) scans are used; the
following are excluded:

- calibrator scans `1421-490_S` and `1934-638_S`
- pulsar check `J1644-4559_S`
- reference scans `*_R`
- noise-diode scans `*_ND_S` and `*_ND_R`

There are 50 ProxCen_S observations. 39 of them have all 16 files (each
12.27 GB, 224 rows) inside one collection. The rule takes 8 of those, evenly
spaced in time: indices `round(i*38/7)`. From each it uses file `_8`, the
middle of the observation, and row 112, the middle of the file.

Realized scope:

- 8 rows spanning 6 days and 7 collections
- 32 samples of 13,631,488 values each
- 436,207,616 primary bytes (109,051,904 per series)

| observation | collection | DATE-OBS (UTC) |
|---|---|---|
| uwl_190429_130235 | 39663 | 2019-04-29T13:02:35 |
| uwl_190429_163748 | 39663 | 2019-04-29T16:37:48 |
| uwl_190430_162008 | 39717 | 2019-04-30T16:20:08 |
| uwl_190501_150103 | 39718 | 2019-05-01T15:01:03 |
| uwl_190502_150319 | 39719 | 2019-05-02T15:03:19 |
| uwl_190503_135452 | 39720 | 2019-05-03T13:54:52 |
| uwl_190504_134200 | 39722 | 2019-05-04T13:42:00 |
| uwl_190504_173107 | 41486 | 2019-05-04T17:31:07 |

## Acquisition

Run from the repository root:

```bash
bash staging/csiro_parkes_uwl_search_mode_u8/download.sh   # ~438.6 MB of exact byte ranges
bash staging/csiro_parkes_uwl_search_mode_u8/build.sh
bash staging/csiro_parkes_uwl_search_mode_u8/verify.sh
```

`download.sh` does the following:

- Calls the anonymous DAP API on every run, `/collections/<id>` for
  licence, access, DOI and title, and `/collections/<id>/data` for fresh
  presigned `s3.data.csiro.au` links, which expire after 48 h.
- Matches each pinned file's DAP id, filename and `fileSize`.
- Fetches two exact HTTP 206 ranges per file:
  - bytes `0–25919`: the primary, HISTORY and SUBINT headers
  - one 54,792,232-byte SUBINT row at `25920 + 112*54792232`
- Resumes interrupted transfers by requesting only the missing tail. Each
  reply must be a 206 with the exact `Content-Range`. Stalls are caught by
  speed limits, not by `--max-time`.
- Validates each header against its pinned SHA-256 and the expected cards:
  - FRONTEND `UWL`, BACKEND `Medusa`, OBS_MODE `SEARCH`
  - SRC_NAME `ProxCen_S`, TRK_MODE `TRACK`, CAL_MODE `OFF`
  - NBITS 8, SIGNINT 0, NPOL 4, POL_TYPE `AABBCRCI`
  - NCHAN 3328, NSBLK 4096, TBIN 0.000128
  - the HDU layout must predict the DAP `fileSize` exactly
- Validates each row: aux-prefix SHA-256, `OFFS_SUB` identifying row 112,
  the 1 MHz `DAT_FREQ` grid, all 3328 `DAT_WTS` nonzero, positive `DAT_SCL`,
  and non-constant planes.
- Checks each full row against its SHA-256 pinned in `sources.tsv`
  (`row_sha256`). These hashes were recorded from the first driver download
  on 2026-10-05, where each row arrived in a single exact 206 range.

The DATA column offset (266,280 bytes) is computed from the SUBINT
`TFORM1..9` widths and cross-checked against `NAXIS1`; it is not hard-coded
blindly.

`discover.sh` (metadata only, about 3.5 MB) re-derives the selection and the
pinned header and aux-prefix hashes from the live API. It is not part of the
acceptance path.

## Verification

`verify.sh` runs `scripts/verify_samples.py` and does not import the build
module. It:

- re-parses each header with its own card reader and recomputes the DATA
  offset
- compares every plane slice by slice against the downloaded row
- checks index SHA-256 and stats, manifest totals, uniqueness, and that no
  stray files are present
- rejects degenerate planes: fewer than 64 distinct codes, a mode share
  above 25%, a mean outside 96–160, a combined 0/255 share above 2%, or
  identical first and last spectra

## Realized output (2026-10-05 build)

- 32 samples, 436,207,616 bytes. The SHA-256 over the concatenated raw
  32-byte per-sample SHA-256 digests, sorted by `sample_path`, is
  `40fef49881f6b3188443e2e05f67e245d04c06daa2459cc67e9827db93d3ba25`.
  Hashing the hex strings instead gives a different value.
- Code distribution: every plane has a mean of 127.49–127.50 and a modal
  share of about 2.6–2.9%.
  - AA/BB planes use 197–256 distinct codes. The minimum code is 37–58 in
    every AA/BB plane except the BB plane of uwl_190503_135452, which
    reaches 0 only through the backend dropout described below.
  - Code 255 (upper clipping) occurs in every AA/BB plane: 999–2,451 values,
    at most 0.018% of a plane. No other AA/BB plane contains code 0.
  - CR/CI planes use all 256 codes. Their rare 0 and 255 values together
    are at most 0.015% of a plane.
  - In the BB plane of uwl_190503_135452, codes 0 and 255 together are
    0.060% of the plane (6,505 dropout zeros plus 1,730 clipped 255s).
- The material is noise-dominated, which is typical of search-mode
  filterbank data. Medusa normalizes every channel of every row to a mean of
  about 127.5 and σ of about 15.9 codes. The bandpass shape and RFI
  amplitude live in the per-channel DAT_SCL/DAT_OFFS columns, which are not
  emitted.
- Medusa output has a native 8-sample periodicity, a backend feature that
  is kept as recorded. Spectra with t % 8 == 0 have a wider code spread than
  the other seven phases (σ 16.4–18.6 against 15.4–15.8 codes). They also
  have higher adjacent-channel correlation, and in AA/BB a mean 0.6–1.3
  codes higher (0.39 in the BB dropout plane).
- Measured over all 32 planes with a stdlib script:
  - Per-channel σ (population σ over all 4096 samples) is 3.27–16.03
    overall. Almost every channel sits at the normalized level: p5
    15.53–15.93, median 15.94, p95 15.95 codes. Only 2–26 channels per
    plane fall below σ = 12.
  - Per-channel means are 126.9–128.1.
  - Lag-1 correlation, as a Pearson coefficient pooled per plane over all
    3327 adjacent-channel pairs of each spectrum used (frequency) or over
    all 3328 channel pairs (t, t+1) (time):

    | Spectra used | Lag-1 range over the 32 planes |
    |---|---|
    | Frequency, pooled over all 4096 spectra | 0.031–0.135 |
    | Frequency, t % 8 == 0 spectra only | 0.098–0.364 |
    | Frequency, all other phases | 0.019–0.088 |
    | Time, pairs (t, t+1) with t % 4 == 0 | 0.020–0.065 |

    The top of the pooled and phase-0 frequency ranges (0.135 and 0.364)
    is the BB plane of uwl_190503_135452 and comes from its dropout spectra.
  - Order-0 entropy is 5.99–6.03 bits per byte.
  - Single planes compress only 1.31–1.32× with zstd -19 and 1.30–1.32×
    with xz -9.
- **Backend dropout in the BB plane of uwl_190503_135452.** It occurs at
  exactly every 512th sample starting at t = 0 (t = 0, 512, …, 3584; 8
  spectra).
  - In those spectra BB drops to code 0 (or near 0) across UWL sub-bands
    5–12 (1344–2368 MHz, channels 640–1663; zeros fall in channels
    640–1658).
  - Each affected spectrum has 798–828 zero channels, 6,505 zero codes in
    total: every zero in that plane.
  - Sub-band means in those spectra are 0.1–32.4 instead of about 127.5,
    and the per-spectrum mean falls to 91.9–94.9.
  - AA, CR and CI of the same row are unaffected (no zeros; sub-band means
    126.5–128.4 at those samples).
  - DAT_WTS is 1.0 for every channel. It is a per-channel, per-row weight,
    so it cannot flag single samples.
  - This is an unflagged zero-power data dropout recorded by the backend,
    not RFI and not clipping. It is kept verbatim, not masked.

## Licence and attribution

Every collection and its `/data` endpoint declare the *Creative Commons
Attribution 4.0 International Licence* (DAP licence 1121, rightsUri
https://creativecommons.org/licenses/by/4.0/). They are `accessLevel Public`
and `dataRestricted FALSE`, with no embargo. Rights statement: "All Rights
(including copyright) CSIRO 2019." Cite, for example:

> Zic, Andrew; Murphy, Tara; Lenc, Emil; Price, Danny; Croft, Steve; Lynch,
> Christene; & Kaplan, David (2019): Parkes observations for project P1018
> semester 2019APRS_02. v1. CSIRO. Data Collection.
> https://doi.org/10.25919/5cd04712280ca

The other collection DOIs used are 10.25919/5ccc698a95721 (_01),
10.25919/5cd09f3af1dd7 (_03), 10.25919/5cd159a5f273a (_04),
10.25919/5cd1b5aad4a5b (_05), 10.25919/5cda6d25e9d25 (_06) and
10.25919/5d9516d17f6d0 (_07).

## Caveats

- UWL data contain RFI (mobile bands, band edges). This is genuine signal
  and is kept. Because Medusa renormalizes each channel per row, RFI shows
  up mainly as a few low-σ channels (2–26 per plane below σ = 12), rare
  clipped 255 codes in AA/BB, and rare 0/255 codes in CR/CI. Its absolute
  amplitude stays in the unemitted DAT_SCL/DAT_OFFS columns.
- The zero codes in the BB plane of uwl_190503_135452 are not RFI. They are
  the unflagged backend dropout described under "Realized output" (8
  single-sample spectra at t = 0, 512, …, 3584, 1344–2368 MHz). They are
  kept verbatim, and that row is deliberately retained.
- Eight rows per series is a modest sample count, chosen because each
  natural row is 54.5 MB and downstream sampling needs only ~100 MB per
  family. The source offers about 50 × 16 × 224 rows.
- The polarization split separates the distinct auto-power and cross-power
  quantities. It does not tile or shard any axis of a product.
