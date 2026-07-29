# Revised MD17 Float64 Development — 2026-07-29

`figshare_rmd17_trajectories_f64` adds computational molecular dynamics, a new
domain and tensor geometry for the 64-bit corpus. It preserves atomistic
coordinate and force arrays shaped `configuration × atom × xyz`.

The candidate was grounded against committed `datasets/*/manifest.toml`,
`attempts/dataset_status.tsv`, and `reports/accepted_recipe_audit.tsv`. No
accepted molecular-dynamics trajectory recipe was present; the closest
biomolecular material was static float32 mmCIF atom coordinates.

## Pinned source and corrections

The source is Figshare article `12672038`, version `3`, DOI
`10.6084/m9.figshare.12672038.v3`. User-run metadata discovery established:

- license: `CC0`
- payload: `rmd17.tar.bz2`
- source bytes: `1,066,301,513`
- source MD5: `cb1a927628d96f2e966025da4fb63d18`
- source SHA-256: `cddeea2ec2c4b22a9de16a9a65a3eeedac5b29da9c99c20bbff0153912bf922b`

The initial draft incorrectly required CC BY 4.0; its guard and manifest were
corrected to the record's more permissive CC0 declaration. A second user run
downloaded the complete archive but exposed a local matcher bug: substring
matching treated `azobenzene` as a duplicate `benzene`. The matcher now uses
exact normalized molecule stems. The archive extraction was also changed from
one bzip2 pass per molecule to one sequential pass for all selected molecules.

## Native-width validation

The five selected molecules are aspirin, benzene, ethanol, malonaldehyde, and
toluene. The builder parses NPY headers without NumPy and requires both
`coords` and `forces` to be C-order little-endian float64 arrays with identical
`configuration × atom × 3` shapes. Float32, big-endian, Fortran-order,
non-finite, malformed, or constant tensors are rejected. Source NPY data bytes
are copied unchanged.

All five molecules contain `100,000` configurations. Atom counts are `21`,
`12`, `9`, `9`, and `15`, respectively.

## Realized output

Build and independent byte verification passed:

- molecules: `5`
- primary samples: `10` (`5` coordinates + `5` forces)
- primary values: `39,600,000`
- primary bytes: `316,800,000`
- median sample: `3,600,000` values
- sample shapes: from `100000 × 9 × 3` to `100000 × 21 × 3`

Raw deflate is deliberately only a baseline, not the target model. Aggregate
ratios were `0.8781` for coordinates and `0.9602` for forces. The force tensors
are therefore challenging bytewise material, but unlike hashes they retain
explicit molecule, configuration, atom, XYZ, and physical-value correlations.
Verification independently rereads every NPY header and compares every output
byte with the source tensor payload.
