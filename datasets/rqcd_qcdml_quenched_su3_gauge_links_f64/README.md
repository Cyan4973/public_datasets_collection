# RQCD qcdML quenched SU(3) gauge configurations (ens_001), float64

Lattice-QCD gauge configurations from the RQCD collaboration's qcdML project
(Daniel Knüttel, University of Regensburg), Zenodo record
[15018324](https://doi.org/10.5281/zenodo.15018324), CC BY 4.0.

- Ensemble: `ldg/rqcd/qcdML/ens_001`. Quenched (pure-gauge) SU(3), Wilson plaquette
  action, beta = 6.0, lattice 8^3 x 16, SU(2)-subgroup heat bath (niter 20,
  project_method "defect"). One Markov chain of 5,000 configurations
  (`config_0.pt` .. `config_4999.pt`).
- Material: per configuration, one torch complex128 tensor
  `U[mu, x, y, z, t, row, col]` with shape (4, 8, 8, 8, 16, 3, 3). That is
  294,912 complex = 589,824 float64 values = 4,718,592 bytes. Every 3x3 block is
  an SU(3) matrix: unitary, det 1, |entries| <= 1, near-full-mantissa doubles.

## Scope

100 configurations, `n = 300 + 47k` for k = 0..99 (300 .. 4953). That gives
471,859,200 primary bytes and 58,982,400 float64 values.

- Thermalization: probe mean plaquettes were 0.695 (config 0), 0.633 (1),
  0.607 (3), 0.603 (25), 0.596 (50) and 0.593 (1000). The chain starts out of
  equilibrium; the beta=6.0 equilibrium value is about 0.594. The first 300
  configurations are skipped.
- A 47-config spacing limits autocorrelation between kept samples.
- The sibling ensemble `ens_004` (record 17494830; 16^3x32, HMC) is deliberately
  excluded. It has a different volume and algorithm.

## Acquisition (`download.sh`)

The whole 22.6 GB archive is never downloaded.

1. Fetch the Zenodo record JSON. Check the title, the physics parameters in the
   description, license `cc-by-4.0`, and the archive size and md5.
2. Range-GET the last 1 MiB of `ens_001_pt.zip`. Parse the Zip64 EOCD locator,
   the Zip64 EOCD and the central directory (5,002 entries) with `struct`.
   Confirm configs 0..4999 exist and that every pinned member in
   `scripts/selected_members.tsv` matches its local-header offset, compressed
   size, uncompressed size and CRC32.
3. Per member, range-GET `offset .. offset + 30 + len(name) + 1024 + csize`.
   Parse the local header (its extra length, 28 here, differs from the central
   one), raw-inflate exactly `csize` bytes (`zlib.decompressobj(-15)`), and
   check the stream end, size and CRC32. Validate the inner torch archive, then
   keep only the exact local-header-plus-data bytes as
   `members/config_<n>.zipmember`. Re-runs skip members that already validate.

Realized download is 452,495,650 bytes (about 452.5 MB; first run 2,448 s): 451,419,446 member bytes, a 1 MiB tail,
and the record JSON.

## Build (`build.sh` → `scripts/qcdml.py build`)

1. Inflate each member.
2. Parse the inner stored zip through its central directory. Its local headers
   use data descriptors, so their sizes are 0.
3. Require `byteorder == little` and `version == 3`.
4. Check `data.pkl` with `pickletools.genops` only. It is never unpickled. The
   required header is `torch._utils._rebuild_tensor_v2`,
   `torch ComplexDoubleStorage`, numel 294912, storage offset 0, shape
   (4,8,8,8,16,3,3) and stride (73728,9216,1152,144,9,3,1). Its SHA-256 must
   match the pinned value.
5. Check that `data/0` is exactly 4,718,592 bytes.
6. Write `data/0` unchanged. complex128 little-endian is interleaved (re, im)
   float64 little-endian. Output goes to
   `samples/<id>/qcdml_ens001_su3_gauge_links_f64/config_<nnnn>.bin`, one sample
   per configuration.
7. Build also checks |entries| <= 1 and the unitarity residual for every link
   matrix.

## Verify (`verify.sh` → `scripts/verify_qcdml.py`)

Verify uses a separate decode path: stdlib `zipfile` for the inner archive,
plus its own outer-member and pickle checks. It:

- re-derives every sample and byte-compares it with the output
- checks the index fields, sha256, min/max, the pinned schedule, and the
  manifest `sample_count` and `total_size_bytes`
- requires, for every link matrix, finite values, |entries| <= 1,
  |U U^dagger - 1| <= 1e-12 and |det U - 1| <= 1e-12 (probes show ~5e-16)
- rejects constant, degenerate or duplicate samples

## Notes

- The values look like high-entropy doubles: the outer DEFLATE ratio is about
  0.956. They are still genuine simulation output with strong algebraic
  structure (SU(3) constraints) and lattice-local correlations.
