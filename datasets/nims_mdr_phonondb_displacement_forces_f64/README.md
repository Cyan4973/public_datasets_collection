# NIMS MDR phonon calculation database: supercell displacement forces (float64)

Primary payload: the raw finite-displacement force sets from Atsushi Togo's
phonon calculation database (formerly phonondb at Kyoto University, now the
"MDR phonon calculation database" collection in the NIMS Materials Data
Repository). Each record is one inorganic crystal (structure taken from the
Materials Project) for which VASP computed the forces on every atom of a
supercell after each symmetry-reduced displacement of one atom by about
0.01 Angstrom. phonopy turns these forces into harmonic force constants.

- One sample = one material = the `forces:` vectors of every entry of the
  top-level `displacements:` block of its `phonopy_params.yaml`, flattened as
  displacement x supercell atom x (x, y, z), little-endian float64, eV/Angstrom.
- Values are written by phonopy with 16 decimals, of which only 8 are
  significant (e.g. `-0.4776346500000000`). Each token is parsed once to the
  nearest binary64. build/verify require that every parsed double equals the
  double of the token rounded to 8 decimals and that `f"{v:.8f}"` reproduces
  it. 743 of 60,053,511 tokens (all |F| > 0.5) carry phonopy's `%.16f` binary64
  print noise (e.g. `0.6119448199999999`, deviation 1e-16). They parse to
  exactly the same double as the 8-decimal value. float32 would not represent
  these values exactly.
- Exact zeros come from site symmetry and are kept.
- Excluded: displacement vectors (almost all 0.01 Angstrom along one axis),
  lattice, positions, masses, PNG plots and `vasp-settings.tar.lzma`. None of
  these are downloaded or emitted.

## Source and license

- Collection: https://mdr.nims.go.jp/collections/d7aab932-8512-4b9a-b93d-b61f6e5e7019
  (10,034 records on 2026-10-09).
- Each record page and `/api/v1/datasets/<id>` give the rights as "Creative
  Commons Attribution 4.0 International"
  (https://creativecommons.org/licenses/by/4.0/). discover.py checked this for
  every pinned record. Credit: A. Togo / NIMS MDR. The Materials Project ids are
  references only.

## Discovery (scripts/discover.py, not part of download.sh)

The HTML collection listing and the JSON API both stop at 10,000 hits, and the
collection filter on the API is ignored. So the population was enumerated over
OAI-PMH (`ListRecords`, `jpcoar_2.0`, UUID keyset resumption tokens). All
10,034 phonon records carry the bulk datestamp `2025-08-25T09:22:51Z`, and the
harvest over 2025-08-25 found exactly 10,034 records titled
"Ab-initio phonon calculation for ..." that each have one
`phonopy_params.yaml.xz` file, which matches the collection count. For each
selected id, `/api/v1/datasets/<id>` supplied the collection membership, the
license, the fileset id, the exact size and the md5.

Selection: keep a record iff `int(sha256(dataset_uuid).hexdigest(), 16) % 2 == 0`.
This rule ignores chemistry, size and content. The full population would give
about 0.9 GB of float64, too close to the 1 GB cap; the half population gives
the realized totals below. No size floor is applied. Small high-symmetry
records are kept.

`sources.tsv` is sorted by dataset UUID, so it does not depend on listing order.

## Scripts

```bash
bash staging/nims_mdr_phonondb_displacement_forces_f64/download.sh   # PARALLEL=4 by default
bash staging/nims_mdr_phonondb_displacement_forces_f64/build.sh
bash staging/nims_mdr_phonondb_displacement_forces_f64/verify.sh
```

- `download.sh` fetches only the pinned `phonopy_params.yaml.xz` filesets. It
  checks each file's exact size and md5, then the aggregate count and bytes,
  then decodes every file to confirm it is a phonopy YAML with displacement
  force sets.
- `build.sh` uses a line state machine. It requires one force row per supercell
  atom for every displacement (atom count taken from the `supercell:` block) and
  writes the samples, `index/<id>/samples.jsonl` (with per-sample shape,
  phonopy version, min/max, zero count and sha256) and
  `filtered/<id>/build_summary.json`.
- `verify.sh` re-derives every sample with an independent regex parser and
  compares bytes. It also checks the index, statistics, duplicates, plausibility
  (|F| <= 1000 eV/Angstrom), degeneracy, floors and the manifest totals.

## Realized scope

Built and verified on 2026-10-09 from 5,078 downloaded files
(178,435,928 bytes of xz):

- 5,078 samples, one per material: 60,053,511 float64 values,
  480,428,088 bytes.
- Values per sample: min 288, p10 1,944, p25 3,888, median 7,776, p75 14,448,
  p90 24,336, max 238,728. 249 samples (4.9%) have fewer than 1,000 values;
  they are kept because no floor rule is applied.
- Shapes: 1-406 displacements (median 26), 20-306 supercell atoms
  (median 108).
- Exact zeros make up 4.56% of all values. Per sample the zero share has
  median 3.5%, p90 16.7% and max 53.5% (high-symmetry cells).
- Per-sample max |F| has median 0.25 eV/Angstrom and p99 0.88; the global max
  is 2.20.
- All records are phonopy 2.17.1 output, so one YAML layout. 16 probed files
  and all 5,078 built files parse with both parsers.
- Aggregate sample-sha256 digest:
  `2945c4f159a342f7ece4bc10338504a3ce5c5f739d67dd4cc3c7fa2b391d019e`.
