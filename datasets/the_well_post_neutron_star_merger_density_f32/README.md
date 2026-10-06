# The Well: post-neutron-star-merger GRMHD density snapshots (float32)

This recipe collects the fluid rest-mass density field from **The Well**
dataset `polymathic-ai/post_neutron_star_merger`. The dataset holds LANL
`nubhlight` simulations of black-hole accretion disks formed after
neutron-star mergers (plus one collapsar), run with general-relativistic
neutrino-radiation magnetohydrodynamics. Each sample is one complete saved
dump of `rho_0` on the simulation's curvilinear log-spherical grid:
192 (log r) x 128 (theta) x 66 (phi) IEEE float32 values, copied byte for
byte from the published HDF5 dataset `/t0_fields/density`.

- Source: <https://huggingface.co/datasets/polymathic-ai/post_neutron_star_merger>,
  pinned at commit `721253cd3220d158d3088c0cce4558dd444d1353`
- Output: 54 samples (6 qualifying simulations x 9 dumps), 1,622,016 values
  each. That is 87,588,864 values and 350,355,456 bytes in total, with
  aggregate SHA-256 `c9f2173f...3f3b4d6`.
- Download: 468,149,859 bytes of exact HTTP byte ranges, covering the
  selected dumps of all 8 files so that the scope rule below can be
  audited. The eight source files are 14,109,638,656 bytes each and are
  never downloaded whole.

## License

The dataset card of the exact pinned revision declares `license: cc-by-4.0`
in its YAML front matter. The Hugging Face API also reports
`cardData.license = "cc-by-4.0"` and the tag `license:cc-by-4.0`, and the
repository is neither gated nor private. `download.sh` re-checks all of these
live and pins the card's SHA-256 (`77ae5197...28bb635`). Attribution:
The Well (Ohana, McCabe, Meyer et al., arXiv:2412.00568) and the nubhlight
papers listed in the card and in `manifest.toml`.

## Relation to the rejected `the_well_mhd64_trajectories_f32`

The only earlier Well attempt, `the_well_mhd64_trajectories_f32`, was
rejected for two reasons:

1. **No license.** That attempt used a *different* repository,
   `polymathic-ai/MHD_64`, which has no license tag. This repository has an
   explicit CC BY 4.0 grant on the exact data objects, so this objection
   does not carry over.
2. **"Not a new homogeneous shape."** Uniform-Cartesian 64^3 turbulence
   cubes were judged to be ordinary dense volumes next to the accepted MRI,
   dose and ERA5 volumes. To be explicit: this recipe is **also a dense,
   regular rank-3 float32 array**. It is *not* one of the sparse,
   unstructured, staggered, adaptive or multiresolution layouts that the
   MHD_64 retry condition lists. That retry condition is scoped to
   `polymathic-ai/MHD_64`, but the judge may reasonably apply the same
   reasoning here. The case for this family rests on modality and on the
   statistics of the field, not on a new array layout:
   - **Modality.** This is astrophysical GR plasma simulation output.
     `tools/autocollect/novelty.py` finds no recipe, registry, ledger or
     downstream hit for `neutron star`, `nubhlight`, `GRMHD`,
     `accretion disk`, `polymathic` or `the well` beyond this candidate. The
     nearest accepted 32-bit volumes are geophysical
     (`weatherbench2_era5_pressure_level_fields_f32`, a lon-lat-level
     spherical shell) and medical (`openneuro_ds000030_t1w_mri_f32`,
     `tcia_eclipse_rtdose_u32`). A queued candidate,
     `pdebench_2d_cfd_turb_m1_density_f32`, is 2-D periodic Cartesian
     Navier-Stokes turbulence, which differs in physics, grid and source.
   - **Grid and statistics (realized output).** The grid is logarithmic in
     radius and focused toward the equator in theta (code coordinate 0..1),
     with phi periodic over [0, 2*pi] and varying fastest. Along the slow
     radial axis the density falls from the disk to the atmosphere floor.
     - Sample maxima run from 0.057 to 1.42 code units, and the floors from
       2.05e-10 to 1.0e-8.
     - One volume spans **7.3 to 9.6 decades** (max / min-positive).
     - Every sample has **1,321,525 to 1,615,630 distinct values** out of
       1,622,016 (median 1,591,496).
     - No value is zero, and the modal value covers at most 3.5% of cells.

## Phi variation ("axisymmetrized" in the card)

The card calls the snapshots "axisymmetrized", yet the stored field varies
in phi. For every sample, the build counts the (r, theta) rows that are
exactly constant along phi (`phi_constant_rows`,
`phi_constant_row_fraction` in `samples.jsonl`):

- the maximum fraction is 12.9% (scenario 4, dump 20)
- 39 of the 54 samples have under 1%
- on average 98.75% of rows vary along phi

The constant rows are atmosphere-floor shells at large radius, and they
shrink as the outflow fills the domain.

## Scope rule

1. **Files.** All 8 published simulation files (train 0, 3, 4, 5, 6, 7;
   valid 1; test 2) are fetched.
2. **Dumps.** From each file, the 9 saved dumps with index
   **20, 40, ..., 180**: a fixed stride of 20 that ends at the final dump.
   These are code times of about 1500 to 9500 in steps of about 1000.
   The Well stores every 10th nubhlight dump, so there are 181 dumps at a
   cadence of about 50 code units, starting at code time about 500.
   **Dump 0 is excluded** as part of the rule, not because of anything in its
   values. It is the earliest saved state, when the disk has not yet spread
   into the initial atmosphere. In probes, 30.8% (scenario 0) and 29.8%
   (scenario 3) of dump-0 rows are constant along phi, and dump 0 has about
   1.0e6 distinct values against 1.32-1.62e6 for the emitted dumps.
3. **Disk presence (per file, evaluated on the fetched data).** A file is
   emitted only if *every* selected dump has maximum density
   >= 1e-2 code units, i.e. it contains the order-unity-normalized disk
   that defines the family. A file whose dumps all fall below is excluded;
   a mixed outcome is fatal. `build.sh` and `verify.sh` both apply the rule,
   and the pinned outcome must be `0, 1, 2, 3, 4, 7`.
   - **Included:** scenarios 0, 1, 2, 3, 4 and 7. Every dump max is
     >= 0.057.
   - **Excluded:** scenarios 5 and 6, the BH-NS disks with M_BH 2.31 and
     2.67. Every fetched dump has max <= 2.2e-5. Even dump 0 (probed for
     scenario 6) peaks at only 2.7e-5. Their fields are dominated by the
     code's radius-dependent density floor:
     - in scenario 6 dump 120, the 1,000 most common values cover 83% of
       cells, each filling an almost complete radial shell
     - the per-shell medians of the two files coincide
     - distinct counts are 150k-860k, and the span is only about 4 decades

     These files are a different numeric regime (4-5 decades lower,
     floor-dominated), not more of the same material. Following
     "homogeneity first", they are left out rather than mixed in. Their
     per-dump statistics are recorded under `scope_rule` in
     `filtered/.../ingest_stats.json`.
4. **One field only.** electron_fraction, temperature, entropy,
   internal_energy, pressure, velocity, magnetic_field and the metric
   `g_contravariant` are not emitted.

54 samples x 6.49 MB is above the ~100 MB that downstream selection uses
per family, and well under the 1 GB cap. A denser stride would mostly add
strongly correlated neighbouring dumps.

## Homogeneity

Every sample is the same quantity (`rho_0`) from the same code and problem
generator (nubhlight `torus_cbc`, SFHo EOS), on the same 192 x 128 x 66
index grid and in the same code-unit convention, stored the same way. All of
them contain a disk peaking at order 0.1-1 code units. The included
scenarios differ in physical setup: black-hole mass and spin, torus
parameters and initial magnetic field. Each simulation therefore has its
own `RHO_unit` and floor level (2.05e-10 for scenarios 1-3, 3.8e-9 to
1.0e-8 for 0, 4 and 7). Values are **not rescaled**. They are the
publisher's stored float32 code units, which is the native artifact. The
simulations ran in double precision and The Well published float32; this
recipe neither widens nor narrows.

Parameters read from each file (`/scalars/a`, root attributes `a`, `mbh`):

| scenario | split | spin a | M_BH (Msun) | dataset-card label | status |
|---|---|---|---|---|---|
| 0 | train | 0.80 | 3.0 | collapsar_hi | included |
| 1 | valid | 0.69 | 2.58 | torus_b10 (GW170817-like, strongest B) | included |
| 2 | test | 0.69 | 2.58 | torus_b30 (intermediate B) | included |
| 3 | train | 0.69 | 2.58 | torus_gw170817 (weakest B) | included |
| 4 | train | 0.80 | 10.0 | torus_MBH_10 | included |
| 5 | train | 0.69 | 2.31 | torus_MBH_2p31 | excluded (no disk >= 1e-2) |
| 6 | train | 0.69 | 2.67 | torus_MBH_2p67 | excluded (no disk >= 1e-2) |
| 7 | train | 0.75 | 6.0 | card lists torus_MBH_2p69, but the file's mbh = 6.0 matches the card's torus_MBH_6 | included |

The card's table lists 9 scenarios, but only 8 files exist. The index
therefore records the file's own `a` and `mbh` instead of card labels.
Scenarios 1-3 share an identical initial torus and dump schedule and differ
only in field strength. Their samples all differ, and verify.sh rejects any
byte-identical pair.

## Conversion

For dump `d`, the bytes `[16777216 + d * 6488064, +6488064)` of the pinned
file are exactly one C-order `(192, 128, 66)` slab of the contiguous,
unfiltered F32LE dataset `/t0_fields/density` (shape
`(1, 181, 192, 128, 66)`). They are written unchanged as one raw
little-endian float32 sample, with axes `log_r, theta, phi` and phi fastest.
The index stores min/max from the stored float32 values, plus min-positive,
distinct count, modal value and count, zero count, phi-constant rows,
SHA-256, dump index, code time (from `/dimensions/time`), source byte
offset, spin and mass.

## Validation

- `download.sh`
  - Checks the live revision API: pinned sha, ungated, CC BY 4.0, exactly
    the 8 HDF5 files.
  - Checks the tree API: sizes, LFS SHA-256 and xet hashes against
    `sources.tsv`.
  - Checks the dataset card: SHA-256 and the license line.
  - Every range must come back as HTTP 206 with the exact `Content-Range`,
    and the response chain must carry the file's pinned LFS SHA-256 or xet
    hash.
  - Ranges resume at byte granularity.
  - Per file, `scripts/well_h5.py` parses bytes 0-65535 and
    11538432-11541093. It checks the superblock v2 lookup3 checksum and EOF
    address, then requires `/t0_fields/density` to have the exact shape,
    dtype, contiguous layout, offset and size and no filter pipeline. It also
    requires 181 strictly increasing times, monotone coordinates and
    consistent spin and mass.
  - Each fetched snapshot must be finite and non-negative (no -0.0) and
    pass loose sanity floors.
- `build.sh` runs the synthetic-HDF5 self-test (`scripts/selftest_well_h5.py`:
  lookup3 reference vectors, parse of a hand-built file, and rejection of
  corrupt checksum, filter, dtype, chunked layout, offset and time order).
  It then:
  - re-parses the local metadata
  - applies the scope rule
  - enforces the family floors on every emitted sample: >= 50% distinct
    values, modal value <= 10% of cells, <= 25% phi-constant rows,
    >= 6 decades between max and min-positive, max >= 1e-2
  - rejects duplicates
  - writes the samples, `samples.jsonl` and `ingest_stats.json`
- `verify.sh` re-derives the scope decisions and the expected sample set,
  and byte-compares every sample with its downloaded range. It recomputes
  all statistics through two decode paths (bit patterns and floats) and
  compares them with the index. It also rejects extra files, duplicates,
  scope or manifest-total mismatches.

## Run

```bash
bash staging/the_well_post_neutron_star_merger_density_f32/download.sh
bash staging/the_well_post_neutron_star_merger_density_f32/build.sh
bash staging/the_well_post_neutron_star_merger_density_f32/verify.sh
```

Logs are written to `${DATA_DIR:-.data}/logs/the_well_post_neutron_star_merger_density_f32/`.
