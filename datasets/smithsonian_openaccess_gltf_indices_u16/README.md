# Smithsonian Open Access glTF Indices UInt16

Collects Smithsonian Open Access / CC0 glTF binary models and emits native
`UNSIGNED_SHORT` mesh index accessors.

The downloader first uses `SMITHSONIAN_GLTF_URLS_FILE=/path/to/urls.txt` when
provided. Without that file, it queries the public Smithsonian Open Access API
with `SMITHSONIAN_QUERY=3d` and extracts direct non-Draco `.glb` asset URLs
from CC0 rows. This avoids the `https://3d.si.edu/cc0` portal page, which has
returned HTTP 403 in this environment.

ZIP URLs are ignored by default because the first successful run showed they
were mostly OBJ/STL/glTF-JSON packages, not GLB assets. Set
`SMITHSONIAN_ALLOW_ZIP=1` only for an exact URL-list retry.

The build rejects `uint32` indices, strided accessors, sparse accessors,
malformed GLB files, and archives that do not contain GLB assets. Natural sample
boundaries are glTF primitive index accessors; independent accessors are not
concatenated.

```bash
datasets/smithsonian_openaccess_gltf_indices_u16/download.sh
datasets/smithsonian_openaccess_gltf_indices_u16/build.sh
datasets/smithsonian_openaccess_gltf_indices_u16/verify.sh
```

Useful knobs:

- `MAX_FILES=24` limits the number of downloaded assets.
- `MAX_DOWNLOAD_BYTES=1000000000` enforces the repository source-size cap.
- `SMITHSONIAN_API_KEY=...` may replace the public `DEMO_KEY` if needed.
- `SMITHSONIAN_GLTF_URLS_FILE=/path/to/urls.txt` is the preferred deterministic
  repair path if API discovery still finds no direct model URLs.
- `SMITHSONIAN_ALLOW_ZIP=1` allows ZIP URLs from discovery or exact URL files.
