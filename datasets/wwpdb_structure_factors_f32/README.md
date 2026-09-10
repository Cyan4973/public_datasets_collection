# wwPDB crystallographic structure factors float32

This dataset contains experimental single-crystal X-ray reflection tables
from the Worldwide Protein Data Bank. It is distinct from the accepted wwPDB
atom-coordinate family and from powder-XRD scans:

- atom coordinates describe points in real space;
- powder XRD is a dense one-dimensional intensity curve; while
- a structure-factor table is a sparse three-dimensional reciprocal-lattice
  record indexed by Miller `h`, `k`, and `l` coordinates.

The emitted primary series are separate homogeneous measured-amplitude and
uncertainty columns. Different physical columns and the three Miller-index
axes are never interleaved. Decimal source values are rounded once to
canonical little-endian float32, following the repository's established
text-to-float32 policy.

wwPDB archive data are distributed under CC0. The existing accepted
`wwpdb_mmcif_atom_coords_f32` recipe independently records the same
archive-level license and attribution policy.

The selection contains five exact structure-factor files. RCSB ignored the
byte-range probes used during exploration and returned complete gzip objects;
the accepted downloader pins those objects by byte size, MD5, and SHA-256.
The optional RCSB search endpoint that returned HTTP 400 is not part of the
accepted path.

Run the exact acquisition, build, and verification workflow from the
repository root:

```bash
bash datasets/wwpdb_structure_factors_f32/download.sh
bash datasets/wwpdb_structure_factors_f32/build.sh
bash datasets/wwpdb_structure_factors_f32/verify.sh
```

The selected complete crystal reflection tables are `1AON`, `1FFK`, `1J5E`,
`2PTC`, and `4V9D`. They emit five measured-amplitude samples and four
uncertainty samples, totaling 4,295,467 values and 17,181,868 bytes. Explicit
`?`/`.` values are omitted independently from the affected field; Miller
indices are validated but not emitted because their observed `0..249` range
does not justify a 32-bit representation.

Every source field remains separate and homogeneous. The aggregate decoded
byte SHA-256 is
`16117e7501951c33722da0816b79e94f81c90d135e3bbf74ec082a9f4d03c5f8`.
