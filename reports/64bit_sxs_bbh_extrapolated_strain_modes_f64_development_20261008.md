# SXS:BBH extrapolated strain modes float64 development

## Outcome

Accepted `sxs_bbh_extrapolated_strain_modes_f64`. It holds native float64 gravitational-wave strain spherical-harmonic modes `r·h_lm/M` from SpEC numerical-relativity binary-black-hole simulations in the SXS Collaboration catalog (2019 Zenodo deposits).

This is the corpus's first numerical-relativity waveform family. It is distinct from `gwosc_event_strain_f32`, which is noise-dominated detector strain at 32-bit. This recipe holds smooth, deterministic, complex-valued simulation output decomposed into spin-weight −2 spherical-harmonic modes, so it is labelled `new_source`, not `new_modality`. The measured breadth verdict is OK. The nearest family by features is `mace_equivariant_linear_weight_f64` at distance 0.0304, but its compression loss is 0.199, far from equivalent.

## Source and rights

- Source: Zenodo community `sxs`, one record per simulation (e.g. record 3301877 for SXS:BBH:0305 and 3326358 for SXS:BBH:1180), file `Lev{N}/rhOverM_Asymptotic_GeometricUnits_CoM.h5`.
- Selection: `discover.sh` and `select_sims.py` list 2,165 `SXS:BBH` records; 2,019 are eligible (cc-by-4.0, with a CoM rhOverM file and metadata.json at the same Lev). The recipe sorts them by SXS number and keeps every 40th, giving 51 simulations from SXS:BBH:0001 to SXS:BBH:2146 (39 Lev3, 6 Lev4, 6 Lev5).
- Pinning: `sims.tsv` pins record id, file keys, sizes and Zenodo MD5s. `download.sh` re-fetches each record JSON and stops on any license, title, size or MD5 change. metadata.json is MD5-checked.
- License: every pinned record declares `metadata.license.id = "cc-by-4.0"`, open access. Cite the SXS catalog (Boyle et al. 2019, CQG 36 195006) and the per-record DOIs.

## Shape and conversion

- Natural record: one HDF5 dataset `Extrapolated_N2.dir/Y_l{l}_m{m}.dat`, a float64 `[N,3]` table of (t/M, Re, Im) chunked `(C,1)` with shuffle(8)+deflate.
- Primary sample: columns 1–2 copied bit-exactly as interleaved Re/Im, one per (simulation, mode), for all 21 modes with 2≤l≤4, including m=0.
- Auxiliary: column 0 (retarded time t/M), bit-identical across the 21 modes and strictly increasing, written once per simulation.
- Not read: N3, N4, OutermostExtraction, l≥5 and the non-CoM file.
- Acquisition: a planner walks each file's HDF5 metadata through a 64 KiB block cache and range-fetches only the needed blocks. Each response must be a 206 with the exact Content-Range. Each chunk must pass its zlib Adler-32 check and inflate to the exact chunk size.
- Build checks: CoM attributes equal metadata `com_parameters`, and the |h22| peak falls inside a window around `common_horizon_time` (realized −13.1…+14.4 M) with an amplitude between 0.02 and 0.6 (realized 0.148–0.414).

## Accepted output

- Simulations: 51; rows per simulation 13,828–34,311
- Primary samples: 1,071 (51 × 21)
- Primary values: 35,837,550
- Primary bytes: 286,700,400
- Sample size: min 27,656, median 31,850, max 68,622 values
- Global value range: −0.4538 … 0.4334
- Auxiliary: 51 time axes, 853,275 values, 6,826,200 bytes
- Download: 466,201,597 bytes (5,939 × 64 KiB blocks plus the 77.6 MB control file), against 4.75 GB of whole files
- SHA-256 over the ordered per-sample sha256 list: `17f89cf24346d0abc1bf1b9aedb5e935115d87885f314eb75aba748155917b40`

Known properties, kept as source data:
- SXS:BBH:0001 (equal mass, no spin) has 10 odd-m modes that are only symmetry-noise, at ~1e-7 to 1e-6.
- In the ~15 aligned-spin simulations, ±m modes are near-mirrors (relative difference 1e-6 to 5e-2). No pair is exact, and precessing runs differ by order unity.
- Every mode includes the early junk-radiation segment.

## Judge checks

- `gate.py`: PASS, no warnings.
- `verify.sh` run by the judge: exit 0.
  - Re-decoded all 51 simulations and byte-compared all 1,122 samples, including sha256 and min/max.
  - Matched the manifest counts and sizes.
  - Control check: 100 of 100 SXS:BBH:1180 range blocks identical to the MD5-verified whole file.
- The synthetic HDF5 self-test passes.
- `build.sh` and the Python scripts have no network access and contain no credentials.
- Decode correctness, independent of the recipe's verify path:
  - Using each file's own chunk row count (48 distinct values, 1261–2295), the worst derivative discontinuity at a chunk boundary is 6.5× its neighbours across 51 files × 5 modes × Re/Im. No chunk is misplaced.
  - The h22 phase runs in the same direction in all 51 simulations, so Re/Im are not swapped.
- Bytes (struct inspection):
  - No zeros, all values unique, no fill and no duplicate sample hashes.
  - Trailing-zero fractions are ~6% for most samples, as expected for full precision. In small negative-m modes the excess zero bits sit at a fixed absolute bit position (~2⁻⁶⁰), which is floating-point cancellation from mixing with the dominant mode, not upstream rounding.
- Rights: all 51 saved record JSONs are cc-by-4.0, open, published 2019-07; a live re-probe of record 3326358 matched.
- Novelty:
  - `novelty.py --url/--terms`: only same-host hits. No SXS, numerical-relativity or waveform-mode recipe, registry row, ledger row or downstream entry.
  - The type, instrument and archive keys have 0 matches.
- Notes:
  - Cosmetic documentation errors: the README states "values span about 1e-9 to 0.4" (actual non-zero magnitudes reach ~1e-15 and the range is ±0.45), and the `sxs_modes.py` docstring says 1 MiB blocks (actual 64 KiB).
  - The driver's same-host archive cap (zenodo.org) applies, so the user must sign off before commit.
