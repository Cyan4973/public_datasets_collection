# NORDIF UF-1100 EBSD Kikuchi patterns uint8

This recipe collects raw 8-bit electron backscatter diffraction (EBSD)
Kikuchi patterns from Zenodo record
[6634354](https://doi.org/10.5281/zenodo.6634354). The deposit is by Bergh,
Ånes and Wenner (2022) and supports the article "Intermetallic phase layers in
cold metal transfer aluminium-steel welds with an Al-Si-Mn filler alloy". It
is licensed CC BY 4.0. Each sample is one 240x240 uint8 detector frame (57,600
values) recorded at one beam position of an SEM raster scan across a weld
cross-section.

Instrument chain, the same for both maps (from `Setting.txt`): Hitachi
SU-6600 SEM at 20 kV, 70° specimen tilt, magnification 1800, and a NORDIF
UF-1100 EBSD detector. The `[Acquisition settings]` are 240x240 px, gain 10,
20 fps and 49,950 µs exposure. The `[Calibration settings]` (gain 15, other
exposures) and the 800x800 `[Electron image]` resolution describe other
images and are ignored.

## Scope

| map | grid (rows x cols) | step | `.dat` size | rows kept | patterns |
|-----|--------------------|------|-------------|-----------|----------|
| II  | 59 x 208 | 0.10 µm | 706,867,200 B | 0, 8, …, 56 (8) | 1,664 |
| III | 64 x 323 | 0.05 µm | 1,190,707,200 B | 0, 8, …, 56 (8) | 2,584 |

That is 4,248 patterns and 244,684,800 bytes of primary output. Both maps
together hold 32,944 patterns (1.9 GB), which is over the 1 GB cap, so the
recipe keeps every 8th scan row. This spreads the subset over the full height
of each map, which crosses the Al / intermetallic / steel layering. A single
contiguous block would not. Every scan point of a kept row is emitted.

Excluded:
- `I_EBSD.dat`: 1,292,668,928 bytes, but its declared 109x207 grid needs
  1,299,628,800, so the file is truncated.
- Calibration, background and acquisition BMPs and SEM area images: these are
  different processes or derived products.
- Other NORDIF deposits with different pattern geometry (60x60 Ni,
  480x480 Si).

## Format and conversion

`EBSD.dat` is NORDIF's `Pattern.dat`: a headerless stack of uint8 patterns,
each row-major 240x240, written in scan-raster order (row by row, x fastest).
The geometry comes only from `Setting.txt`: `[Acquisition settings] Resolution`
and `[Area] Number of samples` (rows x cols, cross-checked against
`Height/Step` and `Width/Step`). Both `.dat` sizes equal rows x cols x 57,600
exactly. A metadata probe confirmed the raster order. Pattern-centre intensity
drifts monotonically down the 59 rows of map II (135→161, the phase layering)
and stays flat along a row.

Row r of a map with C columns is the byte range
`[r*C*57600, (r+1)*C*57600)`. `download.sh` fetches each kept row as its own
HTTP Range request. `build.sh` splits it into C patterns and writes each one
unchanged to `samples/<id>/ebsd_kikuchi_pattern_u8/<map>_r<row>_c<col>.bin`.
No rescaling, background correction or binning is applied. Saturated 255 and 0
values are genuine detector output and are kept.

## Integrity

- `download.sh` re-checks the live record: title, `cc-by-4.0`, open access,
  and the size and MD5 of each used file. It pins the `Setting.txt`
  MD5/SHA-256 and re-parses the acquisition geometry.
- For each row it requires HTTP 206 with the exact
  `Content-Range: bytes start-end/total` and the exact length. It rejects any
  row that holds a pattern with fewer than 16 distinct values. A failed row is
  discarded and re-requested, because `curl -C -` does not compose with `-r`.
- The whole-file MD5s cannot check byte ranges, so per-row SHA-256 values are
  pinned in `row_sha256.tsv` in this recipe. `download.sh` enforces them when
  the file is present and always writes the realized values to
  `downloads/<id>/row_sha256.tsv`. The pins were taken from the first
  driver-run download (2026-10-06, 244,736,926 bytes in 105 s, every row 206
  on the first attempt). `build.sh` and `verify.sh` check all 16 rows against
  them.
- `verify.sh` does not reuse the build code. It re-parses `Setting.txt`,
  re-derives the expected sample list, and checks the row pins. It
  byte-compares every sample with its source slice, recomputes the per-sample
  statistics, rejects constant or degenerate patterns and duplicate rates above
  0.5%, and checks the manifest totals.

## Realized output

- 4,248 samples × 57,600 uint8 values = 244,684,800 bytes; II 1,664, III
  2,584. No constant or byte-identical duplicate patterns.
- Values span 5..255 (251 distinct overall; 166–241 distinct per pattern,
  median 212); mean 128.71; no zeros. zlib -9 ratio is 0.75–0.81 per pattern.
- Value 255 makes up 2.35e-5 of all values (≈1.4 pixels per pattern). It comes
  from fixed detector hot pixels: (117,217) is 255 in every pattern and
  (120,34) in about a third; two others are rare. There is no broad signal
  clipping: the next-highest values in a pattern are around 212–242. Hot
  pixels are genuine raw detector output and are kept as stored.
- The diffraction signal sits on a smooth, vignetted backscatter background.
  Mean intensity varies by scan row (about 106–144) as the scan crosses the
  weld's phase layers. After dividing out the static background (map mean
  pattern) and the dynamic background (31 px box blur), band contrast is only
  about ±1–2.5% of background. Even so, these residuals correlate at 0.65–0.95
  between adjacent scan points but around 0 (−0.15..0.34) for random pairs in
  the same map. The patterns therefore carry position-dependent Kikuchi
  structure, not just a static background plus noise.
- Aggregate SHA-256 of all samples in index order:
  `e66e79ec7451768f4747d37ca61a13cad123b005f575bc81985ee27f13d4ec67`.

## Run

```bash
bash staging/zenodo_nordif_ebsd_kikuchi_patterns_u8/download.sh   # ~245 MB of ranges
bash staging/zenodo_nordif_ebsd_kikuchi_patterns_u8/build.sh
bash staging/zenodo_nordif_ebsd_kikuchi_patterns_u8/verify.sh
```

Downloads go to `.data/downloads/zenodo_nordif_ebsd_kikuchi_patterns_u8/` and
logs to `.data/logs/zenodo_nordif_ebsd_kikuchi_patterns_u8/`. `DATA_DIR`
overrides `.data`.
