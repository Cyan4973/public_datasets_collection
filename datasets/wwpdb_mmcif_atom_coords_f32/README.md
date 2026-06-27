# wwPDB mmCIF Atom Coordinates Float32

This staged recipe collects a bounded set of public wwPDB mmCIF coordinate
files and emits one `float32` Cartesian atom-coordinate stream per structure.

Defaults:

```sh
WWPDB_IDS=6VXX,7K00,1CRN,4HHB,1AON,6LU7,1TUP,2PTC
WWPDB_URL_BASE=https://files.wwpdb.org/download
WWPDB_MAX_FILE_BYTES=50000000
WWPDB_MAX_TOTAL_BYTES=200000000
```

The downloader uses exact public URL patterns:

```text
https://files.wwpdb.org/download/<PDB_ID>.cif.gz
```

The build parses local `.cif.gz` files with Python stdlib only. It extracts the
looped `_atom_site.Cartn_x`, `_atom_site.Cartn_y`, and `_atom_site.Cartn_z`
columns, writes triples as little-endian `float32`, and rejects structures with
missing, non-finite, tiny, or constant coordinate payloads.

Usage after the user-run external download:

```sh
bash staging/wwpdb_mmcif_atom_coords_f32/download.sh
bash staging/wwpdb_mmcif_atom_coords_f32/build.sh
bash staging/wwpdb_mmcif_atom_coords_f32/verify.sh
```

To override the default structures:

```sh
WWPDB_IDS=1CRN,4HHB bash staging/wwpdb_mmcif_atom_coords_f32/download.sh
```

or provide exact URLs:

```sh
WWPDB_URLS_FILE=/path/to/urls.txt bash staging/wwpdb_mmcif_atom_coords_f32/download.sh
```
