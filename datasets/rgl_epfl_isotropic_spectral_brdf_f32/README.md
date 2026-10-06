# EPFL RGL Material Database: Isotropic Spectral BRDF Tensors (float32)

Measured spectral BRDFs of real material swatches from the EPFL Realistic
Graphics Lab (RGL) material database, acquired with the lab's pgII
goniophotometer and stored in the adaptive parameterization of Dupuy & Jakob
(2018). The recipe emits the native float32 `spectra` tensor of every
isotropic material, one sample per material.

- Source: <https://rgl.epfl.ch/materials> (files on
  `https://d38rqfq1h7iukm.cloudfront.net/media/materials/<name>/<name>_spec.bsdf`)
- License: CC0 1.0. The database page
  <https://rgl.epfl.ch/pages/lab/material-database> says: "Licensing
  conditions Unless otherwise noted, all material data is licensed under the
  Creative Commons Zero ( CC0 ) license." Every material panel on the materials
  page links the CC0 1.0 deed, and no material lists an exception.
  `download.sh` re-checks both on every run.
- Citation: Jonathan Dupuy and Wenzel Jakob. *An Adaptive Parameterization for
  Efficient Material Acquisition and Rendering.* ACM TOG 37(6), Art. 274
  (SIGGRAPH Asia 2018). DOI 10.1145/3272127.3275059.

## Scope

| Set | Materials | Spectra shape | Bytes per sample | Kept |
| --- | ---: | --- | ---: | --- |
| isotropic, 32x32 outgoing grid | 49 | (1, 8, 195, 32, 32) | 6,389,760 | yes |
| isotropic, 48x48 (`irid_flake_paint1_fine`) | 1 | (1, 8, 195, 48, 48) | 14,376,960 | yes |
| isotropic, 64x64 (`cg_sunflower`) | 1 | (1, 8, 195, 64, 64) | 25,559,040 | yes |
| anisotropic (`aniso_*`, `ilm_aniso_*`, `weta_*`) | 11 | (17, 8, 195, 32, 32) | 108,625,920 | no |

Realized output: 51 samples, 88,258,560 float32 values, 353,034,240 bytes.
Download: 51 files, 397,553,744 bytes, plus two small HTML pages.

The two finer-grid isotropic files are kept as their own natural records. They
measure the same quantity on the same wavelength and incident grids, at a
finer outgoing resolution. `irid_flake_paint1_fine` is a separate, finer
measurement of the swatch behind `irid_flake_paint1`, and upstream lists the
two as separate materials. The index carries a `shape` per sample.

The anisotropic files are excluded. They sample 17 incident azimuths (a
different measurement regime), are about 111 MB each, and together (about
1.2 GB of float32 spectra) would exceed the 1 GB primary cap.

Materials: 24 TeckWrap vinyl wrapping films (`aurora_white`, `cc_*`,
`cg_sunflower`, `chm_*`, `cm_*`, `satin_*`, `vch_*`), 6 acrylic felts,
5 coloured papers, 4 Colodur wall-paint swatches, 5 ILM film-prop samples,
3 iridescent car paints, 1 LAIKA ceiling paint, plus cardboard, a maple leaf
and a Labsphere Spectralon reflectance standard.
Measurement pipeline versions range from 2.0 to 3.3. The values reflect the
pipeline version that produced each file. All 51 files share the
format, field layout, wavelength grid, and Jacobian-scaled convention
(`jacobian` flag = 1).

## Payload

`spectra` is the spectral reflectance term the official reader
(rgl-epfl/brdf-loader, `powitacq.inl`) interpolates bilinearly over the
outgoing grid. It then forms
`BRDF(lambda) = spectra(sample; phi_i, theta_i, lambda) * NDF / (4 * sigma)`.
Axes in C order are `phi_i` (1), `theta_i` (8 incident elevations, 0 to
pi/2, material-specific), `wavelength` (195 bins, 358.6 to 1001.9 nm, shared),
then outgoing grid row and column.

Values are kept bit-for-bit. Exact zeros are real stored values, not missing
data. They come in two kinds:

- whole outgoing cells that are zero at all 195 wavelengths
  (out-of-domain or unmeasured cells of the parameterization);
- isolated zero wavelength bins inside measured cells where the signal is
  low (the UV end, absorption bands, the non-blue bins of a dark blue paint).
  No value is negative anywhere, so these look clamped to zero upstream.
  That is an inference, not something upstream documents.

Each index row records `zero_count`, `zero_fraction`, `negative_count`,
`distinct_bit_patterns`, `min` and `max` (from the stored float32).

Realized statistics (first build, 2026-10-06):

- Whole-tensor zero fraction runs from 0.78% (`chm_light_blue`) to 25.0%
  (`ilm_solo_m_68`), median 9.6%. In single theta_i slices it reaches about
  27% for `leaf_maple` and 38% for `ilm_solo_m_68`.
- No NaN, Inf or negative values.
- 0.69 to 0.97 million distinct bit patterns per 32x32 tensor; 1.84 million
  for the 48x48 tensor and 2.89 million for the 64x64 one.
- Per-material maxima range from 0.457 (`ilm_solo_m_68`) to 339.85 (the
  specular peak of `chm_mint`). These are Jacobian-scaled values, not albedos.

Not emitted: `luminance` (derived from `spectra`), `vndf`, `ndf`, `sigma`
(fitted parameterization tensors), `valid` (per-cell mask), `phi_i`,
`theta_i`, `wavelengths`, `version`, `description`, `jacobian` (metadata).

## Files

- `materials.tsv`: the pinned selection, sorted by name. Columns: material,
  outgoing resolution, size, S3 ETag (single-part MD5; it matched all 51
  downloaded files), SHA-256 (recorded at the first full download on
  2026-10-06 and now required),
  Last-Modified, `spectra` byte offset (it shifts with the description length),
  pipeline version, tags, and description (the exact header string).
- `download.sh`: fetches the license and materials pages and checks the CC0
  sentence, the CC0 deed link, and that every pinned URL is still listed. It
  then fetches each spec file resumably (`curl -C -`, stall-based abort) into
  `.part`. Before renaming, it checks size, MD5 against the ETag, the pinned
  SHA-256, and the full tensor semantics (`rgl_brdf.py check-file`). It
  writes `downloads/<id>/download_plan.tsv` with the realized hashes.
- `build.sh`: local only. Re-checks each source and parses the header (version
  1.0, the exact 12 fields, non-overlapping in-bounds payloads, spectra float32
  with the pinned shape and offset, wavelength grid, theta_i grid, jacobian
  flag, description). It then writes `samples/<id>/rgl_isotropic_spectral_brdf_spectra_f32/<material>.bin`,
  `index/<id>/samples.jsonl` and `filtered/<id>/ingest_stats.json`.
- `verify.sh`: re-parses each source in memory with a separate parser. It
  byte-compares every sample with its source field, and recomputes NaN/Inf
  (from exponent bits), zero and negative counts, stored-float32 min/max, a
  1,000-distinct-value floor, per-sample SHA-256 and the pinned aggregate
  SHA-256. It rejects duplicates and checks totals against the manifest.
- `discover.sh` and `scripts/discover_tsv.py`: metadata-only re-derivation of
  `materials.tsv` from the materials page plus 4 KiB range reads, kept to
  document provenance. Neither the download nor the build uses them.

## Tensor file format

Mitsuba/RGL `tensor_file`, little-endian:
`"tensor_file\0"`, u8 major = 1, u8 minor = 0, u32 field count, then for each
field: u16 name length, name, u16 ndim, u8 dtype (1 = uint8, 5 = uint32,
10 = float32), u64 absolute offset, u64 shape[ndim]. The parser was checked by
regenerating the real `cardboard_spec.bsdf` header byte-for-byte from the
parsed field table, and by synthetic build/verify round trips with
corrupted inputs (NaN, all-zero, shape, MD5, jacobian flag, truncation).
