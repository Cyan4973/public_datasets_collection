# ambientCG photogrammetry NormalGL uint16 development

## Outcome

Accepted `ambientcg_photogrammetry_normalgl_u16`: native 16-bit OpenGL tangent-space normal maps at ambientCG's 1K tier, for real-world surfaces captured by height-field photogrammetry.

This family is distinct from the accepted `polyhaven_material_displacement_png_u16`:
- Poly Haven stores single-channel scalar heightfields.
- This recipe stores three-channel interleaved surface-normal vectors (X, Y, Z mapped to 0..65535, Z concentrated near the top).
- The source library (ambientCG) and the capture pipeline are also different.

No normal-map family exists at any width in the local or downstream corpus.

## Source and rights

- Source: the ambientCG public material library.
  - The v2 API (`/api/v2/full_json?type=Material&sort=Alphabet`) listed 2014 materials on 2026-10-08.
  - 356 of them have `creationMethod == "PBRPhotogrammetry"`, filtered client-side because the API ignores the method parameter.
- Download: official `https://ambientcg.com/get?file=<id>_1K-PNG.zip` links, which 302-redirect to the ambientCG Backblaze CDN.
  - Only the STORED `<id>_1K-PNG_NormalGL.png` member of each zip is fetched by HTTP byte range: 614,262,802 bytes across 119 members.
- Pinning: `scripts/assets.tsv` pins, per asset, the zip size, member local-header offset, data offset, member size, central-directory CRC32 and IHDR geometry. `discover.sh` re-derives the table from metadata requests.
- Integrity is CRC32 plus exact size per member rather than SHA-256.
- License: CC0 1.0 Universal. The license page (docs.ambientcg.com/license, fetched 2026-10-08) says: "All ambientCG assets are provided under the Creative Commons CC0 1.0 Universal License. This applies to the downloadable asset files and the material preview renders shown for each asset on the site." The page lists no exceptions, and the API documentation imposes no keys or usage terms.

## Shape and conversion

- Natural record: one material's 1K NormalGL texture.
- Selection: all 356 photogrammetry NormalGL members are 16-bit (327 RGB, 29 RGBA). The full population would decode to about 2.05 GB, over the 1 GB cap, so the bounded subset is every third asset in sorted assetId order: 119 assets.
  - The stride keeps the population's category proportions.
  - It never selects two L/S or A/B/C variants of the same scan.
- Decoding is a strict stdlib PNG decode: chunk CRCs, a single IHDR, no PLTE, contiguous IDAT, a complete zlib stream with no trailing data, exact scanline sizes, and all five filter types. Samples are converted from big-endian to little-endian.
- Alpha: where an alpha plane exists (12 of the selected maps) it must equal 65535 at every texel and is then dropped. Every sample is interleaved R,G,B uint16 LE in row-major texel order, named `<asset>_NormalGL_h<H>_w<W>_c3_u16le.bin`.
- Semantic gates in build and verify, per map:
  - at least 256 distinct values per channel;
  - at most 50% of values are multiples of 257;
  - at least 99% of blue values are at least 32768.
- Representation: `native_numeric`.

## Accepted output

| Item | Value |
|---|---|
| Population | 356 PBRPhotogrammetry materials; 119 selected (indices 0, 3, 6, … in assetId order) |
| Source colour types (selected) | 107 RGB, 12 RGBA (alpha verified constant 65535, dropped) |
| Geometry | 96 × 1024x1024; 20 × 1024x512 (WxH); 1 × 512x1024; 1 × 683x1024; 1 × 1024x171 |
| Categories | 26 (Ground 25, Paving Stones 25, Bricks 15, Rock 11, Gravel 6, Tiles 5, Bark 4, …) |
| Primary samples | 119 |
| Primary values | 337,643,520 |
| Primary bytes | 675,287,040 |
| Median sample | 3,145,728 values |
| Smallest sample | 525,312 values (Footsteps002, 1024x171) |
| Multiples of 257 per map | 0.35% to 3.26% |
| Blue at or above 32768 per map | at least 99.98% |
| Min distinct values per channel | 2,731 (median about 17,000) |
| Maps reaching 65535 | 117 |
| Aggregate payload SHA-256 | `0d73724e7b42f4c9db770d8e24820183f7e9929001cd25f325729d965dcd643a` |
| zlsim | OK; nearest downstream:susy_axial_met at 0.0682 (loss −0.0024); polyhaven displacement at 0.0847 (loss 0.049); own ratio about 1.106 |

## Judge checks

- **Mechanics**
  - `gate.py staging/ambientcg_photogrammetry_normalgl_u16` passed with no warnings.
  - I ran `verify.sh` myself and it passed: selftest with 43 decode cases plus rejection cases, all 119 sources re-decoded and byte-compared, and totals and aggregate hash recomputed.
  - `build.sh` and `verify.sh` have no network calls.
  - The download log shows 119/119 members passing the 206, Content-Range, local-header, CRC32 and IHDR checks.
- **Independent decode:** ffmpeg (`-pix_fmt rgb48le`) output is byte-identical to the stored samples for 6 maps:
  - Asphalt015 (RGB);
  - Rock064, Pizza002 and CorrugatedSteel009 (RGBA);
  - PavingStones054 (683x1024);
  - Footsteps002 (1024x171).
- **Bytes**, checked on all 119 maps with stdlib `array`:
  - R and G per-map means lie between 31,291 and 33,455; B lies in the upper half.
  - Low-byte entropy is 7.70 to 8.00 bits, so the 16-bit width is honest.
  - The multiple-of-257 fraction tracks B==65535 saturation, so there is no x257 upscaling.
  - B==65535 covers at most 8.8% of texels (Rocks024S), natural saturation rather than fill; mode_share is 0.0019.
- **Vector length**
  - Per-map median decoded vector length ranges from 0.709 to 1.000 (median 0.981).
  - Older and rougher maps such as Asphalt015 and Ground076 are shortened, consistent with ambientCG box-downsampling high-resolution normals to 1K.
  - There is no trend by release year, so this is one generation process.
  - The manifest's phrase "unit surface normal" is therefore approximate for some maps.
- **Duplicates:** pairwise 32x32 thumbnail correlation is at most 0.39 (Bricks072 vs Bricks079), and all sample SHA-256 values are unique.
- **Rights:** I fetched the license page and the API documentation myself. CC0 covers the downloadable asset files, and no credentials appear in any script.
- **Novelty:** checked with `novelty.py --url ambientcg.com`, `--url struffelproductions.com`, `--terms ambientcg NormalGL "normal map" tangent-space`, `--type pbr_texture_map --instrument ambientcg_heightfield_photogrammetry --archive ambientcg.com`, and `--list-width 8/16/32`.
  - There are no prior ambientCG or normal-map families.
  - Hypersim camera-normal f16 is an unaccepted staging draft of different material.
  - This is the first acceptance from ambientcg.com.
- **Soft notes, not blocking**
  - Selection is a cap-driven stride rather than a natural boundary, but it is deterministic, pinned, and proportional to the population.
  - Integrity is CRC32 plus size rather than SHA-256.
  - The 1K maps are ambientCG's own downsampled published products.
