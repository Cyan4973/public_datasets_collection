# nmrXiv P90 Bruker 1H zg30 free-induction-decay float64 development

## Outcome

Accepted `nmrxiv_p90_bruker_1h_fid_f64`: raw complex time-domain 1H NMR free-induction decays (FIDs), as written by a Bruker Avance NEO 600 under TopSpin 4.0.5 (`DTYPA=2`, IEEE float64). Source is nmrXiv project P90: an ethanolic extract of *Swertia chirayita* and its VLC/MPLC fractions in DMSO-d6.

There is no NMR material in the local or downstream corpus at any width. Complex quadrature receiver recordings do exist (`rf_iq_baseband`, 16/32-bit), so the novelty kind is recorded as a new quantity (nuclear-magnetization decay), not a new modality. The driver's similarity measurement (zlsim) gives `OK`. The nearest family is `downstream:susy_axial_met_64` at feature distance 0.0653 with a 17.5% compression loss.

## Source and rights

- Source: nmrXiv project NMRXIV:P90, DOI 10.57992/nmrxiv.p90, released 2025-01-17; creators Rutz, Marcourt, Wolfender.
- Archive: `https://s3.uni-jena.de/nmrxiv/production/archive/2d828808-0317-48fe-8679-813f91101b2e/nmr-data-of-ethanolic-extract-and-fractions-of-swertia-chirayita.zip`
  - 1,519,545,194 bytes, classic ZIP, 10,901 DEFLATE members.
  - Central directory: 1,211,969 bytes at offset 1,518,333,203, SHA-256 `e89a52ac4a961e505f5d0f21f627abde725378d28776f515d5d10d6f41c44059`.
- License: CC BY 4.0. `download.sh` re-checks the public nmrXiv API record on every run: spdx_id `CC-BY-4.0`, public and published, the DOI, and `download_url` equal to the pinned URL. DataCite independently lists `cc-by-4.0` for the project DOI, with the per-dataset DOIs as parts.
- Safety: plant-extract spectroscopy only, no personal data in the payload.

## Shape and conversion

- **Natural record:** one Bruker 1D experiment `fid` file of 524,288 bytes, holding 65,536 float64 values (32,768 complex points, interleaved real/imaginary).
- **Group delay kept:** the leading digital-filter group delay (`GRPDLY=76`) is native content.
- **Download:** the archive is never fetched whole. `download.sh` reads the EOCD and the pinned central directory. It then range-fetches every 1D `acqus` (255) and the 152 selected `fid` members by exact local-record ranges, checking Content-Range on each. Each member is inflated with raw DEFLATE and checked against the CD CRC32, its size and its data descriptor.
- **Selection rule** (from parsed acqus; re-derived in download, in build, and independently in verify): `DTYPA=2`, `NUC1=<1H>`, `PULPROG=<zg30>`, `TD=65536`, `PARMODE=0`, `SOLVENT=<DMSO>`, `INSTRUM=<Avance Neo 600>`, TopSpin 4.0.5, BF1 600 MHz. The selected list has a pinned SHA-256 (`dbb65ac9…7362`).
- **Excluded:**
  - 81 `noesyigld1d` 1H FIDs (water presaturation)
  - 7 `deptqgpsp` 13C FIDs
  - 15 `zg30` FIDs from TopSpin 4.0.3 in 2018 (14 in MeOD)
  - all 2D `ser` experiments
- **Conversion:** unpack with the BYTORDA byte order (all little-endian) and write the values bit for bit as little-endian float64. No phasing, group-delay removal, apodization, Fourier transform or scaling.

## Accepted output

| Quantity | Value |
|---|---|
| Primary samples | 152 (76 fractions/extracts × 2 independent acquisitions, 2019-10-04 to 2019-10-20) |
| Primary values | 9,961,472 |
| Primary bytes | 79,691,776 |
| Values per sample (min = median = max) | 65,536 |
| Value range | −2,371,594,424.1875 to 2,771,587,518.8125 |
| Lattice | exact 2^-7 for every value; peaks need 37.3–38.4 fixed-point bits |
| Float32-exact share per sample | 0.33–0.75 (strided scan median 0.514) |
| Integral share | 0.8% |
| Local download footprint | 85,474,751 bytes (about 48.6 MB of byte ranges transferred) |

## Judge checks

- **gate.py:** PASS with no warnings (values 9,961,472, bytes 79,691,776, 152 samples, median 65,536, width 64).
- **verify.sh** (run myself): `verify ok`. Its acqus tally reproduces 152 / 81 / 14 / 1 / 7. It byte-compares every sample against the re-decoded source fid.
- **build.sh:** reads only `.data/downloads`. The scripts contain no credentials.
- **Bytes** (struct, from `/tmp/autocollect/`):
  - Shape: a ring-up of growing alternating values, peak at complex point 77–78 in 148 of 152 samples, a beating decay, then a noise tail (tail RMS 3.3e4–1.55e5).
  - Content: no zeros, no padding, at least 65,485 distinct values per sample, no off-lattice values.
  - Byte-lane entropies: 0.00 / 0.01 / 1.60 / 5.98 / 7.99 / 8.00 / 7.76 / 1.97 (least- to most-significant byte).
- **Width:** a 38-bit fixed-point range on a 2^-7 grid fits neither int32 nor float32. Float64 is the instrument's native `DTYPA=2` format, not a widening.
- **Homogeneity:** every selected acqus shares SW_h 9615.38, NS 16, DE 24.63535, O1 4201.19, DIGMOD 3, DSPFVS 21, DECIM 2080, BF1 600.17, TD 65536 and the QCI probe. Only the automatic RG varies (21.97–43.37).
- **Near-duplicates:**
  - Pair members share no exact values. Their heads correlate 0.64–0.91; their tails have median correlation 0.02.
  - Adjacent fractions' experiment-20 heads correlate at median 0.99, from the shared DMSO and water lines.
  - SHA-256 digests are all distinct.
  - Weakness recorded: a single project with a dominant shared solvent component.
- **Rights:** confirmed in the saved API record and in DataCite (`cc-by-4.0` for 10.57992/nmrxiv.p90).
- **Novelty:** `novelty.py` (URL, terms, type/instrument/archive) found no NMR family locally, in the registry, the ledger or downstream. The closest representation is complex I/Q baseband at 16/32 bits.
