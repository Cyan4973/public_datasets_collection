# ambientcg_photogrammetry_normalgl_u16

Tangent-space normal maps (`NormalGL`, OpenGL Y-up) at 1K resolution for 119
real-world surfaces that [ambientCG](https://ambientcg.com) captured with
height-field photogrammetry. The source PNGs are native 16-bit. Each map is
emitted as interleaved R,G,B `uint16` little-endian, one file per material.

- License: CC0 1.0 Universal (<https://docs.ambientcg.com/license/>): "All
  ambientCG assets are provided under the Creative Commons CC0 1.0 Universal
  License. This applies to the downloadable asset files ..."
- Output: 119 samples, 337,643,520 values, 675,287,040 bytes. Most maps are
  1024x1024x3. 23 are non-square, with 1024 on the longest side.
- Download: 614,262,802 bytes of byte ranges. Only the NormalGL member of each
  zip is fetched.

## Population and selection

- The v2 API (`/api/v2/full_json?type=Material&sort=Alphabet`, paged with
  `offset`) listed 2014 materials on 2026-10-08. Of these, 356 have
  `creationMethod == "PBRPhotogrammetry"`. The API ignores the `method` query
  parameter, and `creationMethodName` reads "Height field photogrammetry" for
  every asset, so filtering is done client-side on `creationMethod`. Procedural
  (Substance), approximated and multi-angle assets are excluded.
- Every one of the 356 `<id>_1K-PNG.zip` files has a STORED
  `<id>_1K-PNG_NormalGL.png` member. All are 16-bit: 327 RGB and 29 RGBA.
- Decoding all 356 would produce about 2.05 GB, over the 1 GB cap. The recipe
  therefore takes every third asset in sorted `assetId` order (119 assets) and
  pins them in `scripts/assets.tsv`. That table also lists the excluded rows
  (`selected = 0`). The subset spans about 26 display categories, including
  ground, paving stones, bricks, rock, gravel, tiles, bark and asphalt.
- `discover.sh` re-derives the table from metadata requests and diffs it
  against the pin. It is optional and not part of the download contract.

## Pipeline

1. `download.sh` sends a range GET for `[local header .. end of member]` to
   `https://ambientcg.com/get?file=<id>_1K-PNG.zip`, which 302-redirects to the
   Backblaze CDN. It requires:
   - HTTP 206;
   - a Content-Range equal to `start-end/<pinned zip size>`;
   - a local header with STORED (method 0), no data descriptor, the expected
     member name and sizes;
   - a payload CRC32 equal to the pinned central-directory CRC;
   - a PNG IHDR matching the pin.

   It then strips the header and stores the bare PNG. Re-runs skip members
   that are already validated.
2. `build.sh` runs a strict pure-stdlib PNG decode: chunk CRCs, contiguous
   IDAT, a complete zlib stream, exact scanline sizes, and all five filters.
   It converts BE to LE and drops the alpha plane, which must be exactly 65535
   everywhere. Each map must also pass these semantic gates:
   - every channel has at least 256 distinct values;
   - at most 50% of values are multiples of 257 (rejects 8-bit maps upscaled
     by x257);
   - at least 99% of blue (Z) values are at least 32768 (outward normals).
3. `verify.sh` re-decodes every source and compares it byte-for-byte with the
   stored sample. It recomputes statistics from the stored files, checks the
   index fields, uniqueness, totals, the aggregate hash, and that the sample
   directory contents match the index exactly.

All scripts run a synthetic self-test first. It covers RGB/RGBA, all filters,
alpha rejection, CRC corruption, x257 rejection, and STORED zip-member
extraction. All scripts honour `DATA_DIR` and log to
`$DATA_DIR/logs/ambientcg_photogrammetry_normalgl_u16/`.

## Deliberate exclusions

- NormalDX: the same data with G inverted.
- Displacement, Roughness, AO, Color.
- 2K/4K/8K resolutions, to avoid resolution duplicates.
- Non-photogrammetry creation methods.
