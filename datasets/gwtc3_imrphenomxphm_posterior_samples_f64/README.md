# GWTC-3 (O3b) Bilby IMRPhenomXPHM Posterior Samples, Float64

Native IEEE-754 float64 **Bayesian posterior draws** from the LIGO/Virgo/KAGRA
GWTC-3 parameter-estimation (PE) data release. For each of the 33 O3b
binary-black-hole (BBH) candidates, the recipe emits 18 physical-parameter
columns of the `C01:IMRPhenomXPHM` analysis. One sample is one parameter's
posterior draws for one event.

## Source

- Zenodo record **8177023** ("GWTC-3 ... Parameter estimation data release",
  version 2, published 2023-10-23, doi:10.5281/zenodo.8177023). It has 76
  files and 23.6 GB: two PESummary HDF5 files per candidate
  (`*_mixed_cosmo.h5` cosmologically reweighted, `*_mixed_nocosmo.h5` not
  reweighted), plus skymaps, contours and notebooks.
- Only the `*_mixed_cosmo.h5` files are used. They are the release's default
  product: their distance prior is uniform in comoving rate.
- File layout, checked on every pinned file during authoring and again by the
  planner at download time:
  - HDF5 superblock v0, v1 object headers and symbol-table groups.
  - The root holds `C01:IMRPhenomXPHM`, `C01:Mixed`, `C01:SEOBNRv4PHM`,
    `history` and `version`.
  - `C01:IMRPhenomXPHM/posterior_samples` is a rank-1 **compound** dataset,
    one record per draw.
  - Each record has 138 to 177 members depending on the event (detector set,
    calibration nodes, derived quantities). Every member is IEEE binary64
    little-endian.
  - Storage is **contiguous and unfiltered**, so each table is one byte span
    of the file.

## Rights

- The record-level license in the Zenodo record JSON is
  `"license": {"id": "cc-by-4.0"}`. It covers every file of the record.
  `download.sh` re-fetches the record JSON and stops if the license, the title
  or any pinned key/size/MD5 changed.
- Attribution: LIGO Scientific Collaboration, Virgo Collaboration and KAGRA
  Collaboration; GWTC-3 paper, Phys. Rev. X 13, 041039 (2023),
  arXiv:2111.03606.

## Selection

`sources.tsv` (33 rows) pins, for each file: event, key, size, Zenodo MD5,
table row count, member count, and table byte offset and length. The rows come
from a metadata-only survey of all 36 `*_mixed_cosmo.h5` files (64 KiB range
reads of the superblock and group structures).

- **Included:** all 33 BBH events that have a plain `C01:IMRPhenomXPHM`
  analysis.
- **Excluded:**
  - The three neutron-star–black-hole candidates GW191219_163120,
    GW200105_162426 and GW200115_042309. They have no plain XPHM run, only
    `C01:IMRPhenomXPHM:HighSpin`/`:LowSpin` runs with different spin priors
    (a different generation regime).
  - In every file, `C01:Mixed`. It is an equal-weight resample of the XPHM and
    SEOBNRv4PHM runs, so it would duplicate XPHM draws.
  - In every file, `C01:SEOBNRv4PHM`, which comes from another code (RIFT) and
    another waveform.
- Table sizes range from 3,341 to 249,520 rows (median 39,475), or 4.7 to
  283 MB per table. The total is 1,849,667 rows and 2,314,275,968 table bytes.
  All 33 events are taken whole. No table is truncated or row-sampled.

## Download strategy (range requests)

The posterior table is most of each file, but the files also hold the other
analyses, PSDs, calibration envelopes, priors and configs. The full 33 files
are 4.65 GB, so fetching them whole would not fit next to the build under the
5 GB cap. `download.sh` therefore runs these steps:

1. Runs the synthetic self-test, then validates the record JSON (license,
   title, pinned key/size/MD5 of all 33 files) and does a one-byte liveness
   range GET.
2. Runs planner rounds. `scripts/gwtc3_pe.py plan` walks each file's HDF5
   metadata through a local 64 KiB block cache. Missing metadata blocks are
   fetched in coalesced ranges by `scripts/fetch_blocks.sh` (206 with exact
   `Content-Range`, exact length).
3. Once an event's `posterior_samples` header is resolved, checks it: it must
   be a compound table, contiguous and unfiltered, with the pinned shape,
   member count and byte span, and every selected member must be IEEE f64.
   The planner then requests that one span. `scripts/fetch_span.sh` fetches it
   resumably, continuing a `.part` file from its current length and checking
   every response's 206/`Content-Range`, with stall detection and no hard
   timeout.
4. Downloads the complete control file GW200322_091133 (21.4 MB) and checks
   it against its pinned MD5.
5. Runs a final plan pass, then `check-tables`: every selected column must be
   finite, non-constant and within physical bounds.

Expected bytes on disk: about 2.38 GB (2.314 GB of tables, about 40–50 MB of
metadata blocks, the 21.4 MB control file, and the record JSON). The first
planner round fetches the 1 MiB head of each file. The metadata dependency
chain then takes about 4 more rounds. Measured
Zenodo range throughput while authoring was about 230 KB/s per stream after a
time to first byte of up to 60 s. Spans are fetched 4 at a time.

## What is emitted

There are 18 primary series, each with 33 samples (one per event). Each
sample has N_draws values (one event's table rows) in source row order, as
raw little-endian float64 at `samples/<id>/<parameter>/<event>.f64`.

| series | unit | role in the analysis |
|---|---|---|
| `mass_1_source`, `mass_2_source` | Msun | source-frame component masses |
| `a_1`, `a_2` | – | spin magnitudes (sampled) |
| `tilt_1`, `tilt_2`, `phi_12`, `phi_jl` | rad | spin angles (sampled) |
| `theta_jn`, `psi`, `phase` | rad | orientation, polarisation, phase (sampled) |
| `luminosity_distance` | Mpc | distance (sampled, cosmologically reweighted) |
| `ra`, `dec` | rad | sky position (sampled) |
| `geocent_time` | GPS s | geocentric coalescence time (sampled) |
| `final_mass_source`, `final_spin` | Msun, – | remnant properties from NR fits |
| `log_likelihood` | nat | log likelihood (ratio) of each draw |

The total is 594 samples, 33,294,006 values and **266,352,048 bytes**.

**Selection rule:** keep one column per physical degree of freedom of the
Bilby run, plus the remnant and the likelihood. Masses are kept in the source
frame only, replacing the sampled detector-frame `chirp_mass`/`mass_ratio`.

**Excluded columns:**

- Algebraic re-parametrisations of the kept columns: `mass_1`, `mass_2`,
  `chirp_mass(_source)`, `total_mass(_source)`, `mass_ratio`,
  `inverted_mass_ratio`, `symmetric_mass_ratio`, `chi_eff`, `chi_p*`,
  `spin_1x..2z`, `cos_*`, `iota`, `zenith`/`azimuth`, `psi_wrapped`,
  `redshift`, `comoving_distance`, `*_infinity_only_prec_avg`, `viewing_angle`
  and `beta`/`psi_J`.
- Constant bookkeeping columns: `pn_*_order`, `maximum_frequency`,
  `recalib_*_frequency_*`.
- Calibration nuisance parameters (`recalib_*_amplitude/phase_*`).
- Per-detector SNRs and times.
- `radiated_energy`/`peak_luminosity`.

## Build and verify

- `build.sh` runs the self-test, then decodes each table from the local span
  using the compound offsets taken from the local metadata blocks. It extracts
  each member with strided `memoryview` casts and writes samples, the index
  (with per-sample `min`/`max`/`sha256` taken from the stored doubles) and
  `filtered/<id>/ingest_stats.json`. That stats file records per-event row
  counts, table member counts and per-column distinct-value counts.
- `verify.sh` re-extracts every column through an independent per-row
  slicing path and checks each of the following:
  - every sample byte-compares to its source column;
  - index fields, sha256 and min/max match;
  - no non-finite, constant or out-of-bounds values, and no sample below
    1,000 values;
  - `mass_2_source <= mass_1_source` row by row;
  - no stray files;
  - manifest series ids, counts and bytes match the output;
  - control: every cached metadata block and the table span of
    GW200322_091133 equal the MD5-verified whole file, and the whole-file
    table decode equals the span.
- `scripts/selftest_pe_h5.py` builds synthetic PESummary-like files
  (compound v1/v3 datatypes, decoy groups, multi-SNOD symbol tables, and a
  chunked shuffle+deflate compound variant). It runs the full plan → fetch →
  build → verify loop offline, and checks that tampered samples, stray files,
  manifest drift, truncated tables, NaN or out-of-bounds values, pinned-span
  drift and non-IEEE members are all rejected.

## Caveats

- The cosmological reweighting resamples the original Bilby draws with
  replacement and re-draws the distance of each copy. Measured on the built
  output (`filtered/<id>/ingest_stats.json`), the distinct fractions are:
  - Distance-independent columns (spins, angles, `dec`, `final_spin`,
    `log_likelihood`): 66.8% distinct overall. The fraction ranges from 97%
    (GW191215_223052: 6,701 of 6,913) down to 47% (GW191216_213338: 117,971
    of 249,520, with a value repeated up to 5 times).
  - `geocent_time`: 46.4% distinct.
  - Distance-dependent columns (`luminosity_distance`, source-frame masses,
    `final_mass_source`, and `ra`, essentially): fully distinct.
  - Repeats are scattered through the row order: in `a_1`, at most 4 pairs of
    adjacent rows are equal per event.
  These are the release's own published draws. They are kept as is, with no
  de-duplication or reordering.
- Draws are close to iid within a column, so mantissas have high entropy.
  Rows are aligned across the 18 series (same draw index), but each series is
  stored separately and never interleaved.
- Weak events (GW200308_173609, GW200322_091133) have posterior tails up to
  about 800 Msun and 30 Gpc. The physical sanity bounds are deliberately
  loose.
- Novelty: the corpus holds GW detector strain (`gwosc_event_strain_f32`) and
  NR waveforms (`sxs_bbh_extrapolated_strain_modes_f64`), but no posterior or
  MCMC sample material. `novelty.py` found only same-host Zenodo matches and
  incidental "posterior" term hits. The GWTC-1 staging probes never produced a
  payload.
