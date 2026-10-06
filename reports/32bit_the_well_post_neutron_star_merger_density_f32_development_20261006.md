# The Well post-neutron-star-merger GRMHD density float32 development

## Outcome

Accepted `the_well_post_neutron_star_merger_density_f32`. The family holds the fluid rest-mass density (`rho_0`) from LANL nubhlight general-relativistic neutrino-radiation MHD simulations of black-hole accretion disks formed after neutron-star mergers, plus one collapsar, as published in The Well. Each sample is one complete saved dump on the simulation's 192 (log r) × 128 (θ) × 66 (φ) curvilinear grid, copied unchanged from native float32.

This is the first astrophysical plasma / GRMHD family in the local corpus, and the downstream corpus has no counterpart. At 32 bits in this collection effort it is the third simulation fluid-field family, after `ahmedml_cfd_surface_mean_pressure_f32` (time-averaged surface pressure on an unstructured mesh) and `pdebench_2d_cfd_turb_m1_density_f32` (2-D periodic compressible-turbulence density, values 0.03–4.8). It is therefore labelled `new_source`, not `new_modality`. It is accepted because its numeric regime is distinct: strictly positive values spanning 7–10 decades per volume, a smooth log-radial falloff and an equatorial disk on a 3-D log-spherical grid, with 28 active float exponents. Any further simulation-field family at 32 bits should face a higher bar.

The earlier Well attempt, `the_well_mhd64_trajectories_f32`, was rejected mainly because its repository (`polymathic-ai/MHD_64`) had no license. This repository carries an explicit CC BY 4.0 grant. The MHD_64 "dense grid is not a new layout" retry condition is scoped to that repository, and later dense-grid 32-bit acceptances did not apply it.

## Source and rights

- Source: Hugging Face dataset `polymathic-ai/post_neutron_star_merger` (The Well), pinned at commit `721253cd3220d158d3088c0cce4558dd444d1353`
- Files: 8 HDF5 simulations (train 0, 3, 4, 5, 6, 7; valid 1; test 2), each 14,109,638,656 bytes. Their LFS SHA-256 and xet hashes are pinned in `sources.tsv`.
- License: CC BY 4.0. The pinned dataset card (README.md, sha256 `77ae5197…28bb635`) declares `license: cc-by-4.0` in its YAML front matter. The API reports `cardData.license = cc-by-4.0`, the tag `license:cc-by-4.0`, and `gated = false`, `private = false`. `download.sh` re-checks all of these live.
- Attribution: Ohana, McCabe, Meyer et al., The Well (arXiv:2412.00568); Miller, Ryan & Dolence, nubhlight (ApJS 241, 30, 2019); and the per-scenario papers listed in the card.

## Shape and conversion

`/t0_fields/density` is a `(1, 181, 192, 128, 66)` IEEE F32LE dataset with no filters, stored contiguously at file address 16,777,216 with size 1,174,339,584. Dump `d` therefore occupies bytes `[16777216 + d × 6488064, +6488064)`. That slab is one C-order `(log_r, theta, phi)` volume with φ varying fastest, and it is written unchanged as one sample.

A pure-stdlib HDF5 reader (`scripts/well_h5.py`) locates the dataset from two small metadata ranges per file. It checks:

- the superblock v2 lookup3 checksum and EOF address
- shape, dtype, layout class, address and size
- that there is no filter pipeline
- that the 181 time values are strictly increasing

**Scope.** Dumps 20, 40, …, 180 are taken from every file, i.e. code times about 1500 to 9500. Dump 0, at code time about 500, is excluded by the stride rule.

A file is emitted only if every selected dump peaks at ≥ 1e-2 code units. Build and verify both evaluate this rule, the result is pinned, and a mixed outcome is fatal.

- **Included:** scenarios 0, 1, 2, 3, 4 and 7.
- **Excluded:** scenarios 5 and 6. Their fields hold only the code's density floor:
  - every dump peaks at ≤ 2.2e-5
  - at r index 30 the density is the same 6.11e-7 at every θ
  - the two files' radial median profiles are identical
  - the top 1,000 values cover 76–77% of cells

Values remain in each simulation's code units; nothing is rescaled. Other fields, such as electron_fraction, temperature, velocity and magnetic_field, are not emitted.

## Accepted output

- Source simulations: 8; emitted: 6 (scenarios 0, 1, 2, 3, 4, 7)
- Dumps per simulation: 9 (indices 20, 40, …, 180)
- Primary samples: 54
- Primary values: 87,588,864
- Primary bytes: 350,355,456
- Sample size: 1,622,016 values (6,488,064 bytes), all samples
- Downloaded: 468,149,859 bytes of exact HTTP 206 ranges. This is two metadata ranges plus 9 dumps for each of the 8 files; the scenario 5 and 6 dumps are kept for auditing the scope rule.
- Per-sample maximum: 0.0569–1.417; per-sample minimum: 2.05e-10 to 1.0e-8
- Dynamic range: 7.27–9.64 decades per sample
- Distinct values per sample: 1,321,525–1,615,630 (median 1,591,496)
- Modal value: at most 3.54% of cells; zeros: none
- Rows constant along φ: at most 12.9%, and under 1% in 39 of 54 samples
- Aggregate SHA-256: `c9f2173f973a3a1bb7fc57f056cea9e9053877d52ca97cef13283ebd33f3b4d6`

## Judge checks

- **Gate:** `tools/autocollect/gate.py` PASS with no warnings (median 1,622,016 values, width 32).
- **verify.sh:** I re-ran it: verify_ok in about 30 s with the aggregate SHA-256 above. build.sh and verify.sh are local-only. The build log shows the synthetic-HDF5 self-test passing all of its rejection cases.
- **Negative tests** (scratch DATA_DIR under /tmp with symlinked downloads), all rejected:
  - one flipped sample byte
  - an index max scaled by 1+1e-7
  - an extra file in the sample directory
- **HDF5 mapping, checked with my own raw scan:** `t0_fields` maps `density` to (16,777,216; 1,174,339,584), followed by electron_fraction, entropy, internal_energy and the rest at a stride of 1,174,339,584, identically in scenarios 0, 5 and 7. The scenario 3 dump 100 response header shows HTTP 206, Content-Range 665583616-672071679 (= 16777216 + 100 × 6488064), and an etag equal to the pinned xet hash.
- **Bytes:**
  - Radial medians fall about 8 decades from the disk to the outer floor, and θ profiles peak at the equator.
  - The median relative std along φ is 0.22–0.29, so the field is truly 3-D despite the card's "axisymmetrized".
  - Trailing-zero mantissa bits follow a geometric distribution, so this is full float32.
  - Adjacent selected dumps share 0–2.5% identical values (median |Δlog10| 0.12–0.40).
  - Scenarios 1, 2 and 3 at the same dump share 0–4% identical values (median |Δlog10| 0.21–0.48). No near-duplicates.
  - zstd -6 ratio: 1.10–1.29.
- **Rights:** the local card and revision.json, plus my own live API probe on 2026-10-06, all show cc-by-4.0, ungated and public, at sha 721253cd.
- **Novelty:** `novelty.py` matches only this staging recipe and its ledger row; there are no registry or downstream term hits. Labelled `new_source` given AhmedML and PDEBench (see Outcome).
- **Caveats accepted as-is:**
  - Only 6 independent simulations; diversity within each comes from 9 time-separated dumps.
  - The card's scenario table lists 9 scenarios for 8 files, and file 7's mbh = 6.0 contradicts its card label. The index records each file's own `a` and `mbh` instead.
  - Per-dump content hashes are not pinned in the recipe. Integrity rests on the pinned revision, the LFS/xet identity carried by every 206 response, the superblock checksum and the layout validation.
