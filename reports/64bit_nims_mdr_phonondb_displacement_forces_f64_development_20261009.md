# NIMS MDR phonon database supercell displacement forces float64 development

## Outcome

Accepted `nims_mdr_phonondb_displacement_forces_f64`. It holds the raw finite-displacement force sets from Atsushi Togo's phonon calculation database: the "MDR phonon calculation database" collection in the NIMS Materials Data Repository, formerly phonondb at Kyoto University.

One sample is one inorganic crystal. It contains the VASP forces on every supercell atom after each symmetry-reduced displacement of one atom by 0.01 Å. phonopy builds harmonic force constants from exactly these values.

The material is new as a source. The closest existing modality is the molecular-dynamics atomic forces of `figshare_rmd17_trajectories_f64` (five small organic molecules, kcal/mol/Å). This recipe instead covers periodic inorganic crystals computed with plane-wave PBEsol VASP in finite-displacement supercells, in eV/Å on a 1e-8 grid with exact site-symmetry zeros. On the bytes, zlsim places it OK, with nearest family `globalcmt_mrt_f64` at distance 0.0888.

## Source and rights

- Collection: https://mdr.nims.go.jp/collections/d7aab932-8512-4b9a-b93d-b61f6e5e7019 (10,034 records).
- Enumeration: the HTML listing and the JSON API both cap at 10,000 hits, so the collection was harvested over OAI-PMH (`jpcoar_2.0`, keyset tokens). The harvest found exactly 10,034 records titled "Ab-initio phonon calculation for ...", each with one `phonopy_params.yaml.xz`.
- Selection: keep a record if `int(sha256(uuid), 16) % 2 == 0`. This is content-blind and yields 5,078 records.
- Pins: `sources.tsv` is sorted by UUID and pins fileset id, exact size and MDR md5 per file. The download totals 178,435,928 bytes.
- License: every record's API entry gives rights "Creative Commons Attribution 4.0 International" (https://creativecommons.org/licenses/by/4.0/), creator Atsushi Togo. Materials Project ids appear only as references; the files are NIMS/Togo calculation outputs.

## Shape and conversion

- Decoding: each file is lzma-decompressed. The decimal tokens under every `displacements[*].forces` entry are parsed once to IEEE-754 binary64 and written little-endian, in file order (displacement x supercell atom x xyz).
- Validation: each displacement must have exactly one force row per supercell atom (atom count from the `supercell:` block), and the length unit must be angstrom.
- Precision: phonopy writes 16 decimals of which 8 are significant. 743 of 60,053,511 tokens carry `%.16f` binary64 print noise. Each is checked to be the same double as its 8-decimal rounding, and anything else is fatal.
- Exclusions: displacement vectors, lattice, positions, masses, PNG plots and VASP settings archives are not emitted, and there is no auxiliary series.
- Width: the values are real-valued decimals that float32 cannot hold exactly, and phonopy stores them as float64.

## Accepted output

- Primary samples: 5,078 (one per material; unique mp-ids, filesets and md5s)
- Primary values: 60,053,511
- Primary bytes: 480,428,088
- Values per sample: min 288, p10 1,944, median 7,776, p90 24,336, max 238,728. 249 samples (4.9%) under 1,000 are natural high-symmetry records; no floor rule was applied.
- Shapes: 1 to 406 displacements (median 26), 20 to 306 supercell atoms (median 108)
- Exact zeros: 4.56% of all values. Per sample the share has median 3.5% and max 53.5%, all from site symmetry.
- Per-sample max |F|: min 0.0006, median 0.25, max 2.20 eV/Å
- phonopy version: 2.17.1 for all 5,078 files
- Aggregate sample SHA-256: `2945c4f159a342f7ece4bc10338504a3ce5c5f739d67dd4cc3c7fa2b391d019e`

## Judge checks

- **Gate:** `python3 tools/autocollect/gate.py staging/nims_mdr_phonondb_displacement_forces_f64` gave PASS with no warnings.
- **Verify:** I ran `bash staging/nims_mdr_phonondb_displacement_forces_f64/verify.sh` myself and it exited 0. The independent regex parser reproduced all 5,078 samples byte-for-byte, and totals matched the manifest. build.sh and phonondb.py make no network calls.
- **Bytes:** a third line parser I wrote reproduced 40 random samples exactly. Physics on those 40:
  - net force per displacement is at most 1.6e-7 eV/Å;
  - the force on the displaced atom opposes the displacement in 100% of displacements;
  - the displaced atom carries the largest force in about 95%;
  - every displacement is 0.01 Å.
- **Distribution:** across 300 random samples (3.56M values):
  - magnitudes peak at 1e-4 to 1e-3 eV/Å;
  - signs are balanced 50/50;
  - no value lies off the 1e-8 grid;
  - the top nonzero value has a 0.012% share (no fill).
- **Rights:** I fetched the MDR API for the first, middle and last record. All are CC BY 4.0, published, open_to_public, in collection d7aab932, by creator Togo, and their fileset id, size and md5 match `sources.tsv`.
- **Homogeneity:** I probed three ~1 KB `vasp-settings.tar.lzma` archives. Each INCAR-force file has GGA=PS (PBEsol), ENCUT=520, EDIFF=1e-8, ISMEAR=0, SIGMA=0.01 — one generation process.
- **Novelty:** the URL and term searches (phonopy, phonon, force sets, phonondb, supercell, vasp, dft) and the type/instrument/archive search found only this candidate and rMD17 forces (local and downstream). zlsim verdict OK, nearest `globalcmt_mrt_f64` at 0.0888.
