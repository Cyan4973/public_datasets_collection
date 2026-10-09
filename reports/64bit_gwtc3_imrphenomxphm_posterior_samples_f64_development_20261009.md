# GWTC-3 IMRPhenomXPHM posterior samples float64 development

## Outcome

Accepted `gwtc3_imrphenomxphm_posterior_samples_f64`: native IEEE-754 float64
Bayesian posterior draws from the LIGO/Virgo/KAGRA GWTC-3 parameter-estimation
(PE) data release, version 2.

This is the first posterior-sample (sampler-output) material in the corpus.
The accepted `gwosc_event_strain_f32` holds detector strain time series and
`sxs_bbh_extrapolated_strain_modes_f64` holds numerical-relativity waveforms.
This recipe instead keeps the posterior draws of physical source parameters
produced by the Bilby nested sampler with the IMRPhenomXPHM waveform model.

## Source and rights

- Source: Zenodo record 8177023, "GWTC-3: Compact Binary Coalescences
  Observed by LIGO and Virgo During the Second Part of the Third Observing
  Run — Parameter estimation data release", published 2023-10-23,
  doi:10.5281/zenodo.8177023 (76 files, 23.6 GB).
- Files used: the 33 binary-black-hole `IGWN-GWTC3p0-v2-<event>_PEDataRelease_mixed_cosmo.h5`
  files. Their keys, sizes, Zenodo MD5s, row counts, member counts and table
  byte spans are pinned in `sources.tsv`. Together the files are 4,645,103,433
  bytes, of which 2,376,852,001 bytes were range-fetched.
- License: CC BY 4.0. The record JSON declares `metadata.license.id =
  "cc-by-4.0"` at record level, which covers every file. `download.sh`
  re-validates the license, title and every pinned key, size and MD5 on each
  run.
- Attribution: LIGO Scientific Collaboration, Virgo Collaboration and KAGRA
  Collaboration; GWTC-3 paper, Phys. Rev. X 13, 041039 (2023),
  arXiv:2111.03606.

## Shape and conversion

- **Table location.** Each file's `C01:IMRPhenomXPHM/posterior_samples` is a
  rank-1 HDF5 compound dataset with one record per posterior draw. Records
  have 138, 142, 173 or 177 members, every one IEEE binary64 little-endian.
  Storage is contiguous and unfiltered.
- **Download.** `download.sh` range-fetches 64 KiB-aligned metadata blocks
  (superblock v0, v1 object headers, symbol-table groups) plus one span per
  event holding the whole table. Every response must be a 206 with the exact
  `Content-Range`.
- **Decode.** A pure-stdlib reader resolves the table and checks it against
  the pinned span. The build then copies the 8 bytes at each selected member's
  compound offset from every row, in source row order.
- **Sample.** One natural record is one event's full posterior column for one
  parameter.
- **Series (18).** `mass_1_source`, `mass_2_source`, `a_1`, `a_2`, `tilt_1`,
  `tilt_2`, `phi_12`, `phi_jl`, `theta_jn`, `psi`, `phase`,
  `luminosity_distance`, `ra`, `dec`, `geocent_time`, `final_mass_source`,
  `final_spin`, `log_likelihood`.
- **Excluded columns.** Algebraic re-parametrisations (detector-frame masses,
  chirp mass, mass ratios, chi_eff, chi_p, Cartesian spins, cosines, redshift,
  comoving distance), constant bookkeeping columns, calibration nuisance
  parameters, and per-detector SNRs and times.
- **Excluded analyses and events.** `C01:Mixed`, a resampled union that
  duplicates the XPHM draws. `C01:SEOBNRv4PHM`, which comes from another code
  and waveform. The three NSBH events, which only have HighSpin/LowSpin runs
  with different spin priors.
- **Caveat: repeated values.** The release's cosmological reweighting
  resamples the draws with replacement and re-draws the distance for each
  copy. As a result, distance-independent columns are 66.8% distinct overall
  (47.3% for GW191216_213338, up to 97.8% for GW200308_173609) and
  `geocent_time` is 46.4% distinct. Distance-dependent columns are fully
  distinct. These are the release's own published draws and are kept
  unaltered. The non-reweighted files total 17.7 GB.

## Accepted output

- Events: 33 (all GWTC-3 O3b BBH candidates with a plain XPHM run)
- Primary series: 18, each with 33 samples
- Primary samples: 594
- Primary values: 33,294,006 (1,849,667 rows x 18)
- Primary bytes: 266,352,048 (14,797,336 per series)
- Minimum sample: 3,341 values (GW200308_173609)
- Median sample: 39,475 values
- Maximum sample: 249,520 values (GW191216_213338, 13.5% of rows)
- Range-fetched bytes: 2,376,852,001 (table spans 2,314,275,968)
- zlsim breadth: OK. Nearest per-series distances are 0.049–0.105.
  `luminosity_distance` alone sits within the redundancy thresholds, at 0.049
  from `jpl_cad_v_rel` with loss 0.0004.

## Judge checks

- **Gate.** `gate.py` passed with no warnings.
- **Verify.** I re-ran `verify.sh` myself and it succeeded:
  - 33/33 events were byte-compared through the independent per-row path;
  - index sha256 and min/max match, as do the manifest totals, and there are
    no stray files;
  - `mass_2_source <= mass_1_source` holds on every row;
  - the control file GW200322_091133 matched its MD5 (19 metadata blocks and
    the table span), and its whole-file decode equals the range span.
- **Local build.** `build.sh` and `verify.sh` use only local files;
  `blockstore.py` and `pe_h5.py` never touch the network.
- **Logs.** The download and build logs postdate the last script edits. The
  download log records `record_ok license=cc-by-4.0`, `tables_ok events=33
  rows=1849667` and `control_ok`.
- **Bytes.** I inspected four events across all 18 series with `struct`:
  - Units and ranges are physical: spins in [0, 0.99], angles in [0, pi] or
    [0, 2pi], masses in Msun, distances in Mpc, `geocent_time` at GPS
    about 1.26e9 with millisecond spread.
  - Mantissas are full float64. No column looks widened from float32, apart
    from 21 near-zero `log_likelihood` values in GW200308, which fits
    cancellation in a likelihood ratio.
  - Row order is iid. No value dominates any sample (mode share at most
    0.0004).
  - The repeat structure matches resampling with replacement:
    distance-independent columns repeat jointly, while distance, `ra` and
    `geocent_time` differ between copies.
- **License.** I opened the stored record JSON: license `cc-by-4.0`, access
  open, LVK collaborations as creators.
- **Novelty.** `novelty.py` found no URL or term matches outside same-host
  Zenodo recipes and this staging draft. Breadth-key queries returned 0
  matches each, there are no MCMC or posterior terms downstream, and the
  vocabulary has no posterior type.
- **Minor README inaccuracy (not material).** The caveat cites
  GW191215_223052 (96.9%) as the most-distinct event; the most distinct is
  actually GW200308_173609 (97.8%).
