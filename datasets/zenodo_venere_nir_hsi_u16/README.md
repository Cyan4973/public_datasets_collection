# Venere NIR Hyperspectral Cube UInt16 — Preflight

This candidate is the main native-uint16 ENVI cube from Zenodo record
`8143550`, *Push-broom NIR-HSI scanning of painting reconstruction, inspired
by Sandro Botticelli's "Venus"*, released under CC BY 4.0.

The selected `venere` pair declares a 410×384×288 little-endian uint16 cube in
band-interleaved-by-line (BIL) order: 45,342,720 values and 90,685,440 payload
bytes. Dark and white reference cubes are intentionally excluded from the
primary family.

Run:

```bash
bash datasets/zenodo_venere_nir_hsi_u16/download.sh
bash datasets/zenodo_venere_nir_hsi_u16/inspect.sh
bash datasets/zenodo_venere_nir_hsi_u16/build.sh
bash datasets/zenodo_venere_nir_hsi_u16/verify.sh
```

The accepted representation is one source-order tensor shaped
`[410 lines, 288 bands, 384 samples]`. Its 45,342,720 native little-endian
uint16 detector values are emitted without scaling or reordering. The ENVI
header and wavelengths remain provenance metadata rather than training values.
