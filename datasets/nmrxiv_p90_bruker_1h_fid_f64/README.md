# nmrXiv P90 Bruker 600 MHz 1H zg30 FIDs (float64)

Raw 1H NMR free-induction decays (FIDs) from the nmrXiv project
[P90](https://nmrxiv.org/project/P90) (DOI 10.57992/nmrxiv.p90, CC BY 4.0):
ethanolic extract of *Swertia chirayita* and its VLC/MPLC fractions, measured
in DMSO-d6 on a Bruker Avance NEO 600 (QCI cryoprobe) with TopSpin 4.0.5 and
pulse program `zg30` (16 scans, TD 65,536, SW 9615.38 Hz).

Each sample is one Bruker `fid` file as written by the spectrometer:
65,536 IEEE float64 values (`DTYPA=2`, `BYTORDA=0`), i.e. 32,768 complex
points stored as interleaved real/imaginary pairs, including the leading
digital-filter group delay (`GRPDLY=76`). No phasing, group-delay removal,
apodization or Fourier transform is applied.

## Scope

- 152 samples = 76 extracts/fractions x 2 independent zg30 acquisitions
  (experiment `20`/`21` and `proton_NN`, recorded about two weeks apart in
  October 2019).
- 79,691,776 primary bytes, 9,961,472 values.
- Excluded by the acqus rule: 81 `noesyigld1d` 1H FIDs (water suppression),
  7 `deptqgpsp` 13C FIDs, 15 `zg30` FIDs written by TopSpin 4.0.3 in 2018
  (14 in MeOD, 1 in DMSO), and all 2D `ser` experiments.

## How it works

- `download.sh` checks the P90 record in the public nmrXiv API listing:
  license `CC-BY-4.0`, public/published, DOI, and archive `download_url`. It
  never fetches the 1.52 GB project ZIP. Instead it range-reads the EOCD and
  the central directory (SHA-256 pinned), then fetches each of the 255 1D
  `acqus` members and the 152 selected `fid` members by its exact
  local-record byte range. Each member is inflated with raw DEFLATE and checked
  against the central-directory CRC32 and size and against its data descriptor.
  The selection made from the parsed acqus files must match a pinned list.
- `build.sh` runs the ZIP and acqus parser self-test on synthetic stdlib
  `zipfile` archives (seekable, and streamed with data descriptors). It then
  re-derives the selection from the local acqus files, decodes every fid with
  the byte order given by BYTORDA, and writes
  `samples/<id>/bruker_1h_zg30_fid_f64/<fraction>__<experiment>.f64` plus
  `index/<id>/samples.jsonl`.
- `verify.sh` uses its own acqus reader to independently re-derive the
  expected set. It re-decodes each source fid, byte-compares it with the
  sample, and checks CRC32, SHA-256, finiteness, distinct-value count, index
  fields, and the manifest totals.

## Notes

- Values lie on a 1/128 lattice with magnitudes up to about 2.6e9. Only about
  half of them are exactly representable in float32, so float64 is the native
  width, not a widening.
- The two acquisitions of each fraction share the same spectrum, so their
  FIDs correlate (r ≈ 0.9 overall). Their noise tails are independent
  (r ≈ 0.02), and each is a separate experiment directory.
