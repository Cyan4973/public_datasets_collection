# Apple Hypersim camera-space normal G-buffer float16 development

## Outcome

Accepted `apple_hypersim_normal_cam_f16`: camera-space geometric surface-normal G-buffers (`normal_cam`, which ignores bump mapping) from Apple's Hypersim photorealistic synthetic indoor-scene dataset. Each sample is the native IEEE binary16 `[768, 1024, 3]` array of one rendered frame, emitted exactly as stored.

This is the first renderer G-buffer family in the corpus. The closest local relative is `ambientcg_photogrammetry_normalgl_u16`, but the two differ in generation process and encoding:

| | `ambientcg_photogrammetry_normalgl_u16` | this recipe |
|---|---|---|
| Generation | photogrammetry | V-Ray scene-geometry G-buffer |
| Frame | tangent space | camera space |
| Encoding | fixed-point uint16 codes | IEEE half, NaN for no-hit pixels |
| Structure | high-frequency micro-detail | piecewise planar |

Novelty is therefore recorded as `new_source`, not `new_modality`. zlsim measured breadth as STRONG: the nearest family is downstream `har_body_acc` at distance 0.1411.

## Source and rights

- Source: the official Apple ML Research CDN, `docs-assets.developer.apple.com/ml-research/datasets/hypersim/v1/scenes/<scene>.zip`.
  - One stored (method 0) zip per scene, 1.0 to 15.8 GB.
  - 68 of the 200 selected zips use zip64 records.
  - Zip sizes and Last-Modified are pinned per scene in `sources.tsv`.
- Metadata: `apple/ml-hypersim` at commit `3463c5c4a75f3cbfc65ed31cfd6e87204b3a2254`.
  - Split CSV, sha256 `47b7cce1…5ce6`.
  - `README.md`, sha256 `1141b494…851d`.
- License: CC BY-SA 3.0 Unported.
  - The README states "The Hypersim Dataset is licensed under the Creative Commons Attribution-ShareAlike 3.0 Unported License".
  - `download.sh` checks that sentence.
  - Attribution and the share-alike obligation are documented.

## Shape and conversion

**Selection.** Scene index `k*457//200` over the 457 sorted public scenes, for k = 0..199. The camera is `cam_00`, with a `cam_01` fallback for 3 scenes. The frame is the median public frame id. The cap comes from the 1 GB output limit.

**Acquisition.** Range GETs only: tail, then EOCD/zip64, then the central directory, then the local header plus the member. The local-header name and the CRC-32 are checked, and each member is fully HDF5-decoded at download time. 175,549,036 member bytes were kept.

**Decode.** A pure-stdlib HDF5 reader adapted from the accepted bosch cnc_h5 reader. It handles superblock v0, a symbol-table root group, v1 object headers and layout v3 chunked with a v1 B-tree. Each frame has 192 deflate chunks of 96x128x1, and the complete chunk grid is required. A synthetic self-test runs at the start of `build.sh`.

**Policy.** No value is clipped, renormalized or imputed.
- No-hit pixels are the quiet NaN `0x7e00` on whole pixels and are kept bit-exact.
- Fatal: any finite magnitude above 8, fewer than 50% finite pixels, or fewer than 50% unit-norm pixels.
- Degenerate frames are dropped and recorded, and verify re-derives the drop set. A frame is degenerate if one triplet covers more than 90% of it or it has fewer than 256 distinct words. Realized drops: ai_003_001 and ai_039_003.

## Accepted output

- Scenes selected: 200. Emitted: 198, from 198 distinct scenes across 51 volumes.
- Primary values: 467,140,608.
- Primary bytes: 934,281,216.
- Sample size: 2,359,296 values for every sample.
- Realized range: -5.64453125..4.63671875, from filter overshoot in 17 frames.
- NaN: 4,104,339 words (0.88%) in 65 frames; the worst frame is ai_004_010 at 19.5%. Inf: 0.
- Per-frame unit-norm pixel fraction: minimum 0.745, median 1.0.
- Per-frame top-triplet fraction: median 0.32, maximum 0.77. 30 frames exceed 0.5 and are flagged but kept, because they are planar walls.
- Distinct words per frame: minimum 732, median 18,673, maximum 30,058.
- Aggregate SHA-256 of sorted sample bytes: `87a0edf8dac498fa53b8591871ce3cdd9c5259f2a356fa052c890cf5f950eda0`.

## Judge checks

- `gate.py`: PASS, no warnings.
- `verify.sh`: run myself, exit 0 in 3m18s, with matching counts and drop set.
- Independent decode: my own TREE-signature chunk parser plus zlib, compared against the samples. Result: 6 members × 192 chunks, 0 mismatched words. The datatype message confirms binary16.
- Byte statistics with `struct` on 8 samples:
  - Norms are about 1 and z is mostly positive.
  - Chunk-seam differences equal within-chunk differences.
  - NaN is only `0x7e00`, on whole pixels.
- Near-duplicates: maximum pairwise exact-triplet match of 7% over 19,503 pairs.
- Rights: I read the README line in the sha256-pinned copy. BY-SA has precedent in 11 accepted recipes. This is the first recipe from this host.
- Hygiene: no network calls in build or verify, and no credentials.
- Novelty: only the ambientCG normal-map family matched. Label corrected from `new_modality` to `new_source`.
