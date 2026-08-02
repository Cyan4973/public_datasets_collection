# Venere NIR Hyperspectral Cube UInt16 Development — 2026-08-02

`zenodo_venere_nir_hsi_u16` adds a new native-16-bit domain and geometry:
cultural-heritage imaging spectroscopy represented as a three-dimensional
push-broom detector cube.

## Source, license, and selection

Zenodo record `8143550`, *Push-broom NIR-HSI scanning of painting
reconstruction, inspired by Sandro Botticelli's "Venus"*, was published by
Paolo Oliveri, Giorgia Sciutto, Cristina Malegori, and Rodigo Rocha de Oliveira
under CC BY 4.0 with DOI `10.5281/zenodo.8143550`.

The selected source pair is:

- `venere.hdr`: 5,918 bytes,
  MD5 `9c3aaf32039f039143f60b8535a86b61`
- `venere.raw`: 90,685,440 bytes,
  MD5 `523a952df4261d6f3692df74bdc7c699`

The same record also contains dark and white calibration-reference cubes.
Those are excluded because they represent calibration quantities rather than
the painting-scene detector field. A separate heritage-science record found
during discovery is not mixed into this family.

## Native layout and semantics

The exact ENVI header declares:

- samples: `384`
- lines: `410`
- spectral bands: `288`
- data type: `12` (unsigned 16-bit integer)
- byte order: `0` (little-endian)
- interleave: `bil` (band interleaved by line)
- header offset: `0`
- wavelengths: 288 increasing values from `896.15` to `2502.4` nm

The output is one natural tensor in source storage order with shape
`[410 scan lines, 288 spectral bands, 384 spatial samples]`. Values are native
sensor digital numbers, not dark/white-corrected reflectance. No scaling,
calibration, interpolation, band removal, spatial cropping, or reordering is
performed.

## Quality assessment and verified output

The complete payload scan found:

- primary samples: `1`
- primary values: `45,342,720`
- primary bytes: `90,685,440`
- value range: `[5,501, 65,535]`
- distinct values: `47,423`
- zero values: `0`
- saturated values: `46` (`0.00010145%`)
- constant spectral bands: `0`
- mean detector value: `18,474.962677`

The output payload SHA-256 is
`893fc6ebc2bc76744aae9116895d5f11ffb2b80529e1cd7aacaab8fc6460bb1e`.

Build and verification passed. Verification rechecks Zenodo identity/license,
header and payload sizes/MD5s, reparses the ENVI declaration and wavelength
vector, rescans every detector value and every band, and confirms that the
emitted uint16 element stream is byte-identical to the validated source field.
