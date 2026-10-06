# NanoMegas ASTAR SPED diffraction patterns uint8 (NiTi wire)

This recipe collects raw 8-bit scanning precession electron diffraction
(SPED) patterns from two CC BY 4.0 Zenodo deposits by the Institute of
Physics of the Czech Academy of Sciences (FZU, Prague):

- [15183487](https://doi.org/10.5281/zenodo.15183487): Molnárová, Tyc,
  Klinger, Šittner, data for "Reconstruction of martensite variant
  microstructures in grains of deformed NiTi shape memory alloy by TEM"
  (Materials Characterization, 10.1016/j.matchar.2024.114084). Figs 5-8 and
  S5.
- [15183021](https://zenodo.org/records/15183021): Tyc, Šittner, data for
  "Martensitic transformation induced by cooling NiTi wire under various
  tensile stresses" (Applied Materials Today, 10.1016/j.apmt.2024.102448).
  Figs 9-11. The record's DOI field holds the article DOI, so it is cited by
  record id.

Both readmes say the `.blo` files are "raw data from Astar mapping". Each
sample is one 144x144 uint8 image of the TEM fluorescent screen, taken by
the ASTAR external camera while the beam precesses at one probe position of
a 3–4 nm-step scan over a NiTi wire lamella. That is 20,736 values per
pattern: sparse Bragg spots on a dark background, with a saturated direct
beam.

## Scope

All eight NiTi blockfiles share one geometry: `IMGBLO` header magic 258, VBF
offset 4096, DP_SZ 144, 200 kV. Each file size equals
`DP_offset + NX*NY*(6 + 144*144)` exactly. The full set holds 226,341
patterns (4.69 GB), which is over the 1 GB cap. The recipe keeps every 16th
scan row (rows 0, 16, 32, …), which spreads the subset over the full height
of every map, and it emits every scan point of each kept row.

| scan | record | grid NX x NY | step | camera length (header) | acquired | rows kept | patterns |
|------|--------|--------------|------|------------------------|----------|-----------|----------|
| Fig5  | 15183487 | 135 x 162 | 3 nm | 78.4 mm  | 2023-12-06 | 11 | 1,485 |
| Fig6  | 15183487 | 158 x 178 | 4 nm | 77.2 mm  | 2023-11-13 | 12 | 1,896 |
| Fig7  | 15183487 | 175 x 175 | 4 nm | 77.0 mm  | 2024-01-24 | 11 | 1,925 |
| Fig8  | 15183487 | 147 x 204 | 4 nm | 77.0 mm  | 2024-01-30 | 13 | 1,911 |
| FigS5 | 15183487 | 154 x 170 | 4 nm | 264.8 mm | 2024-02-23 | 11 | 1,694 |
| Fig9  | 15183021 | 152 x 147 | 4 nm | 144.9 mm | 2024-03-18 | 10 | 1,520 |
| Fig10 | 15183021 | 215 x 216 | 4 nm | 77.0 mm  | 2023-10-19 | 14 | 3,010 |
| Fig11 | 15183021 | 134 x 155 | 4 nm | 100.0 mm | 2024-04-30 | 10 | 1,340 |

That is 14,781 patterns and 306,498,816 bytes of primary output, from
306,587,502 bytes of row ranges plus 8 × 4,096 header bytes.

The operator notes stored in each header (verbatim, Czech/English shorthand)
are:

- Fig5: `ss3nm, spot10,CL77mm,15precesi`
- Fig6: `77MM, 0.6, 4NM, PPF6`
- Fig7: `sspot9, 77mm, 0.7 uhel, 4nm step, ppf10`
- Fig8: `77mm, 9sspot, 4nm step, 0.7 dg, , 10ppf`
- FigS5: `JAKO ZONA PREDTIM, ALE cl JE 290` ("like the zone before, but CL is 290")
- Fig9: `CL145mm,ss4nm,prec0p6,6precesi`
- Fig10: `SS4nm,CL77mm,precese0p7`
- Fig11: `CL100mm,8precesi,ss4nm,`

`build.sh` copies the decoded header fields and notes into
`filtered/<id>/ingest_stats.json`: step, camera length, scan rotation,
acquisition time, and flags.

Excluded:
- Figure PNGs. These are rendered figures.
- The `.res` files. These are ACOM template-matching results, not
  acquisition data. Each one declares `582 + NX*NY` points (814 for S5) and
  names its source scan, which ties it one-to-one to the blockfiles above.
  They are not needed for decoding.
- The virtual bright-field image in each `.blo`. It is a derived per-scan
  image and is not emitted.
- Blockfiles from other deposits: a TiO2 `.blo` (record 8165269, a different
  lab and material) and a FeCr 512x512 `.blo` (record 13881947, a different
  pattern geometry).

## Homogeneity

The eight scans come from one lab, one TEM + ASTAR setup, one material
system (NiTi #5 wire in the "15 ms" heat-treatment state named in the scan
and `.res` source names) and one detector geometry. They
share one value lattice: 144x144 uint8 camera DN, stored unprocessed. Three
things vary between scans, and the variation is genuine:

- **Background offset and exposure.** The ASTAR camera exposure, gain and
  brightness were set per session, so background level differs by scan.
  Realized per-scan value statistics (DN, all kept patterns):

  | scan | min | p01 | median | mean | p99 | p99.9 | zeros | 255s | distinct/pattern (min, median) |
  |------|-----|-----|--------|------|-----|-------|-------|------|--------------------------------|
  | Fig9  | 0  | 0  | 2  | 4.06  | 34  | 253 | 7.29% | 1.9e-4 | 90, 121 |
  | Fig5  | 0  | 1  | 5  | 7.25  | 32  | 104 | 0.078% | 1.2e-4 | 74, 94 |
  | Fig7  | 0  | 2  | 6  | 7.44  | 31  | 143 | 0.052% | 1.5e-4 | 84, 105 |
  | Fig10 | 0  | 4  | 14 | 19.17 | 81  | 248 | 0.013% | 2.9e-4 | 138, 169 |
  | FigS5 | 2  | 10 | 21 | 23.78 | 75  | 227 | 0 | 4.7e-4 | 121, 151 |
  | Fig11 | 0  | 10 | 26 | 31.95 | 116 | 255 | 1e-7 | 2.0e-3 | 150, 193 |
  | Fig6  | 4  | 16 | 33 | 39.27 | 116 | 252 | 0 | 5.6e-4 | 163, 191 |
  | Fig8  | 12 | 32 | 51 | 54.68 | 108 | 208 | 0 | 4.0e-4 | 143, 162 |

  Within a scan the mean pattern intensity varies little between positions
  (for example Fig8 53.5–56.1, Fig7 7.1–8.3). FigS5 varies more
  (18.9–37.1). Fig9 has the lowest black level, and its background is
  partly clipped at 0 (7.3% zeros). That is genuine camera output and is
  kept.
- **Camera length.** It is 77 mm on five scans and 100, 145 and 265 mm on
  the others. This changes the spot spacing on the detector, not the value
  lattice.
- **Precession angle.** It is 0.5–0.7° where noted.

These settings are the normal operating range of one acquisition process.
They are not different quantities or scales, so this is one family. The
recipe records per-scan settings and statistics. It does not equalise
them.

## Format and conversion

The NanoMegas blockfile layout follows the RosettaSciIO `blockfile` reader:

- A 4096-byte header: `IMGBLO`, then
  `<HIIIHHHHHddIHId` = magic, VBF offset, DP offset, flags, DP_SZ,
  DP rotation, NX, NY, scan rotation (0.01°), SX and SY (nm), beam energy (V),
  SDP, camera length (0.1 mm) and acquisition time (serial date). Then 8
  centring and 14 distortion doubles, and a latin-1 note at byte 240.
- An NX*NY uint8 virtual bright-field image at byte 4096.
- From the DP offset, NX*NY frames in (NY, NX) raster order. Each frame is
  `u16 0x55AA` (bytes `AA 55`), a `u32` frame index, and 20,736 uint8
  pixels in row-major order.

Scan row r is therefore the contiguous byte range
`[DP_offset + r*NX*20742, DP_offset + (r+1)*NX*20742)`. `download.sh`
fetches each kept row as its own HTTP Range request. `build.sh` checks every
frame prefix (marker `0x55AA` and index `row*NX + col`), drops the 6 prefix
bytes, and writes the 20,736 pixel values unchanged to
`samples/<id>/sped_diffraction_pattern_u8/<scan>_r<row>_c<col>.bin`. No
rescaling, background subtraction, centring or binning is applied.

The values 255 and 0 are genuine camera output and are kept. The direct beam
saturates in every kept pattern, with 1–89 pixels at 255, and strong
reflections can saturate too. Low-offset scans have true zeros in the
background. See Realized output.

## Integrity

- `download.sh` re-checks both live records: title, `cc-by-4.0`, open
  access, and the size and MD5 of each used `.blo`.
- It fetches the 4096-byte header of each file, pins its SHA-256, and parses
  the header tuple. That tuple is IMGBLO, magic 258, VBF offset 4096, the
  pinned DP offset, DP_SZ 144, NX and NY. It also requires that the VBF ends
  at the DP offset and that `DP offset + NX*NY*20742` equals the file size.
- For every range it requires HTTP 206 with the exact
  `Content-Range: bytes start-end/total` and the exact length. It checks
  every frame prefix in every row and rejects constant patterns. A failed
  range is discarded and re-requested, because `curl -C -` does not compose
  with `-r`.
- The whole-file MD5s cannot check byte ranges, so per-row SHA-256 values
  are pinned in `row_sha256.tsv` in this recipe. `download.sh` enforces them
  when that file is present and always writes the realized values to
  `downloads/<id>/row_sha256.tsv`. The pins come from the first driver-run
  download: 2026-10-06, 306,848,042 bytes in 195 s, every range 206 on the
  first attempt. `build.sh` and `verify.sh` check all 92 rows against them.
- `verify.sh` does not reuse the build code. It re-reads the headers by
  byte offset and re-derives the expected sample list. It checks the header
  and row pins, re-checks every frame prefix, and byte-compares every sample
  with the pixel raster of its source frame. It also recomputes the
  per-sample statistics. It rejects constant patterns, patterns with fewer
  than 8 distinct values, and duplicate rates above 0.5%, and it checks the
  manifest totals.
- The parsers were self-tested on a synthetic blockfile (header, VBF, 5x33
  frames with spots and a saturated beam). `build` output matched the
  generated patterns byte for byte, and the validators rejected a wrong
  marker, wrong index, constant pattern, short payload, wrong
  Content-Range, wrong header size or grid, and a tampered sample. The real
  probed headers of all eight files pass the header validator.

## Realized output

- 14,781 samples × 20,736 uint8 values = 306,498,816 bytes. By scan: Fig5
  1,485, Fig6 1,896, Fig7 1,925, Fig8 1,911, FigS5 1,694, Fig9 1,520, Fig10
  3,010 and Fig11 1,340. Every frame prefix matched. There are no constant
  and no byte-identical duplicate patterns.
- Values span 0..255 (all 256 used); overall mean 23.75. Per-pattern
  distinct values range from 74 to 224.
- Saturation: 255 makes up 4.6e-4 of all values. Every pattern has at least
  one 255 pixel. The median per pattern is 1–9, except Fig11 at 43 (maximum
  89). Across sampled patterns the 255 pixels cluster at the detector centre
  (rows 69–74, columns 70–73), so they are the saturated direct beam. No
  fixed hot pixel appears elsewhere. The direct beam is genuine raw output
  and is kept.
- Zeros make up 0.77% of all values, almost all of them in Fig9 (7.3%,
  clipped low background). Fig5, Fig7 and Fig10 have a few zeros in every
  pattern; Fig6, Fig8 and FigS5 have none.
- The signal is position-dependent. After subtracting each scan's mean
  pattern, adjacent scan points correlate at a median of 0.79–0.99 per
  scan, while random pairs in the same scan sit near 0 (medians −0.14 to
  0.20). Pairs that land in the same martensite variant reach up to 0.99.
  The patterns therefore carry variant- and grain-specific Bragg-spot
  structure, not a static background plus noise.
- Neighbours are not near-duplicates byte for byte. Adjacent patterns share
  only 13–35% identical pixels (70% in the very dark Fig9). Compressing a
  pattern with its neighbour as zlib context saves only 3–7%.
- zlib -9 ratio per pattern (median): Fig9 0.24, Fig5/Fig7 0.41–0.42, Fig10
  0.54, FigS5 0.56, Fig6/Fig8/Fig11 0.66–0.69. The material is fairly
  compressible: dark backgrounds with sparse spots.
- Aggregate SHA-256 of all samples in index order:
  `f6792033f01fb98b996caae1137f399c95f7996768066db827c102c35d95b974`.

## Run

```bash
bash staging/zenodo_astar_niti_sped_patterns_u8/download.sh   # ~307 MB of ranges
bash staging/zenodo_astar_niti_sped_patterns_u8/build.sh
bash staging/zenodo_astar_niti_sped_patterns_u8/verify.sh
```

Downloads go to `.data/downloads/zenodo_astar_niti_sped_patterns_u8/` and
logs to `.data/logs/zenodo_astar_niti_sped_patterns_u8/`. `DATA_DIR`
overrides `.data`.
