# EPFL RGL isotropic spectral BRDF float32 development

## Outcome

Accepted `rgl_epfl_isotropic_spectral_brdf_f32` from the EPFL Realistic Graphics Lab (RGL) material database.

This is a new modality for the corpus: measured, goniometric, spectral bidirectional reflectance tensors of real material swatches. The corpus already holds satellite surface-reflectance rasters and 1-D soil MIR spectra. Neither samples the incident and outgoing directions, so this family sits beside them rather than duplicating them. No BRDF or BSDF material exists locally or downstream at any width.

## Source and rights

- Source: the RGL material database, <https://rgl.epfl.ch/materials>. Files are `https://d38rqfq1h7iukm.cloudfront.net/media/materials/<name>/<name>_spec.bsdf` (S3 origin behind CloudFront, anonymous HTTPS, Last-Modified 2018-11-01 to 2019-02-04).
- Pinned selection: 51 isotropic `*_spec.bsdf` objects, 397,553,744 bytes. Each file is pinned by byte size, S3 ETag (equal to the single-part MD5 for all 51) and SHA-256 in `materials.tsv`.
- License: CC0 1.0. The database page <https://rgl.epfl.ch/pages/lab/material-database> says: "Unless otherwise noted, all material data is licensed under the Creative Commons Zero ( CC0 ) license." Its measurement-service section requires CC0 consent for samples sent in by others, which covers the ILM- and LAIKA-provided swatches. Every material panel on the materials page links the CC0 1.0 deed through a shared template, and no material lists an exception. `download.sh` re-checks the grant sentence, the deed link and the 51 listed URLs on every run.
- Citation: J. Dupuy and W. Jakob, *An Adaptive Parameterization for Efficient Material Acquisition and Rendering*, ACM TOG 37(6) 274 (2018), DOI 10.1145/3272127.3275059.

## Shape and conversion

Each natural record is one material's spectral BSDF file.

- **Parsing.** The Mitsuba/RGL `tensor_file` v1.0 header is parsed: magic, u8 major/minor, u32 field count, then per field the name, ndim, dtype, u64 offset and u64 shape. The `spectra` field (dtype 10, float32) is checked against its pinned shape and pinned offset; the offset shifts with the description length and NDF resolution.
- **Payload.** The field's `4 * prod(shape)` bytes are emitted unchanged, in source C order (phi_i, theta_i, wavelength, outgoing row, outgoing column).
- **Shapes.** 49 materials are (1, 8, 195, 32, 32), `irid_flake_paint1_fine` is (1, 8, 195, 48, 48) and `cg_sunflower` is (1, 8, 195, 64, 64). All share the 195-bin 358.63–1001.89 nm grid, θ_i from 0 to π/2, and `jacobian` = 1.
- **Not emitted.** `luminance` (derived from `spectra`); the fitted parameterization tensors `vndf`, `ndf` and `sigma`; the `valid` per-θ bitmask; and the metadata fields `version`, `description`, `phi_i`, `theta_i`, `wavelengths` and `jacobian`.
- **Excluded files.** The 11 anisotropic files sample 17 incident azimuths, which is a different regime, and together hold about 1.2 GB of spectra, over the cap.
- **Zeros.** Exact zeros are kept as genuine stored values. They are either whole out-of-domain or unmeasured (θ, cell) spectra, or scattered zero bins in low-signal regions. No value is NaN, Inf or negative.

## Accepted output

- Source files validated: 51 (397,553,744 bytes), plus two HTML evidence pages (15,918 and 325,137 bytes)
- Primary samples: 51 (the entire isotropic population)
- Primary values: 88,258,560
- Primary bytes: 353,034,240
- Minimum and median sample: 1,597,440 values (6,389,760 bytes; 49 samples)
- Larger samples: 3,594,240 values (48×48) and 6,389,760 values (64×64)
- Zero fraction: 0.78% (`chm_light_blue`) to 24.99% (`ilm_solo_m_68`), median 9.6%
- Per-material maximum: 0.457 (`ilm_solo_m_68`) to 339.85 (specular peak of `chm_mint`)
- Distinct bit patterns: 692,986–966,433 per 32×32 tensor; 1,837,784 (48×48); 2,891,008 (64×64)
- Aggregate SHA-256 of all samples, in material order: `468bf9defd2410df5c18237703d3665d0c0e477b50d567172b10dd53dff06ff9`

## Judge checks

- **Gate.** `python3 tools/autocollect/gate.py staging/rgl_epfl_isotropic_spectral_brdf_f32` passed with no warnings.
- **Verify.** `bash staging/.../verify.sh` exited 0 when I ran it. It re-parses every source in memory, byte-compares each sample with its source field, and rechecks size, MD5, SHA-256, counts, min/max and the aggregate hash.
- **Provenance.** The driver's latest `download.latest.log` (02:48) is newer than every recipe file and shows `license_ok=1 cc0_link_ok=1 page_spec_files=62 pinned_listed=51`, liveness HTTP 206, and all 51 files re-validated.
- **Local-only build.** `build.sh` reads only `.data/downloads/<id>/`.
- **Headers.** My own `struct` parser, written separately from the builder's code, confirmed the header layout, offsets, shapes, wavelength grid and θ_i grid on four files, including the variants with a 512-bin NDF and the finer 48×48 and 64×64 grids.
- **Width.** Trailing-zero mantissa bits follow the geometric ½ⁿ pattern and the low bytes are equally common, so the full float32 width is used with no lattice. Exponents span 15–105 binades.
- **Axis order.** Lag-1 change is 2–3% along wavelength against 8–67% along the outgoing grid, consistent with the claimed C order.
- **Zero structure.** For cardboard, 116,220 of 116,224 zeros fall in whole (θ, cell) spectra. There is no hard clipping: at most 4 values equal any material's maximum.
- **Physics and scale.** Spectralon's median is about 0.99, the LAIKA paint matched to an 18% gray card reads 0.18–0.20, `paper_blue` is high in blue and low in red, and green felt peaks at 550 nm. The scale is consistent from pipeline v2.0 (`cm_white`) to v3.3 (`paper_white`, Spectralon).
- **Duplicates.** A pairwise scan of all 51 samples (shared distinct-value fraction and mean-spectrum distance) found no duplicates. The largest overlap is 8.2%. `irid_flake_paint1_fine` is a separate measurement, not a resampled copy.
- **Rights.** I read the CC0 sentence on the license page and confirmed the shared per-material CC0 template. No record carries a copyright, non-commercial or proprietary notice. No credential strings appear in the recipe.
- **Novelty.** `novelty.py` with the RGL URL, the CloudFront host and terms (brdf, bsdf, goniophotometer, goniometric, spectral reflectance, material appearance, rgl, epfl, mitsuba, tensor_file, reflectance, spectralon) found no prior BRDF material anywhere.
- **Byte share.** About 89% of the bytes come from the 32×32 tensors. The builder's summary said about 86%, a small undercount.
