# Blocked: Zenodo Gamma-Ray Spectra UInt16

- Date: 2026-08-02
- Candidate: `zenodo_gamma_spectra_u16`
- Intended domain: gamma-ray detector pulse-height/count spectra
- Intended representation: exact uint16 re-encoding of source decimal counts

## Attempt

A license-first Zenodo search used seven gamma-spectroscopy, scintillator,
radionuclide, and pulse-height queries. It admitted only explicit CC0 or CC BY
records and considered bounded text files in SPE, MCA, TXT, CSV, or TSV form.

The parser accepted only structured `$DATA:`/`<<DATA>>` sections, one-column
integer count arrays, or two-column tables with a strictly increasing energy
coordinate and an exact integer count column. Spectra also had to contain a
power-of-two number of channels between 256 and 65,536, fit uint16 exactly,
and have nondegenerate count distributions.

## Result

- unique records searched: `149`
- records rejected for license: `15`
- records rejected for weak domain relevance: `86`
- bounded plausible text files: `2`
- qualified spectra: `0`

The only plausible files were `Experimental Spectrum.txt` and
`ReconstructedSpectrumDATA.txt`. They proved to be six- and seven-column
analysis tables rather than unambiguous channel/count spectra. Choosing a
column would require undocumented semantic interpretation, so both were
rejected.

No accepted dataset payload was produced.

## Status and retry condition

This Zenodo route is blocked, not a rejection of radiation spectra as a
domain. Retry only with an exact permissively licensed source containing a
documented count field or standard SPE/MCA data section whose complete integer
counts fit uint16. Do not repeat the broad Zenodo keyword search.

Evidence:

- `.data/logs/zenodo_gamma_spectra_u16/discover.latest.log`
- `.data/discovery/zenodo_gamma_spectra_u16/summary.json`
- `.data/discovery/zenodo_gamma_spectra_u16/candidates.tsv`
