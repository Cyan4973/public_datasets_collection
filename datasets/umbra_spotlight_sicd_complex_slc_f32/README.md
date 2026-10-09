# umbra_spotlight_sicd_complex_slc_f32

Ten whole Umbra X-band spotlight SAR complex single-look images (SICD 1.2.1,
`RE32F_IM32F`) from the CC BY 4.0 Umbra Open Data Program on AWS. Each one is
emitted as its full `rows x cols x (I,Q)` float32 array, converted from
big-endian to little-endian.

## Material

- **Quantity:** complex radar reflectivity, i.e. the in-phase and quadrature
  components on the SICD slant-plane range/azimuth grid. The phase is kept;
  the magnitude is not detected, calibrated or log-scaled.
- **Regime:** 2023 Umbra-04/05/06 collects, all with these properties:
  - SPOTLIGHT, MONOSTATIC, VV polarization (from `METADATA.json`; the SICD
    XML says `OTHER`)
  - polar-format algorithm (`ImageFormAlgo PFA`), `Grid/Type RGAZIM`
  - formed by "Umbra Image Formation processor 0.6.x" (0.6.1.2, 0.6.2.0,
    0.6.4.1, 0.6.6.0)
  - about 9.6 GHz, row/col sample spacing about 1.1–1.3 m by 1.3–1.4 m
  - grazing angle 34.7–45.5°
- **Scenes** (one collect each):

  | Scene | Site |
  | --- | --- |
  | Chesapeake Bay | ship_detection_testdata |
  | Tanna Island, Vanuatu | |
  | Strait of Hormuz | ship_detection_testdata |
  | Purdue University farm plot | |
  | Manzanillo, Mexico | ship_detection_testdata |
  | Taparal, Colombia | |
  | NDSU plot, ND | |
  | Magui Payan, Colombia | |
  | Myra, ND | |
  | offshore Angola (7.6°S 12.1°E) | ship_detection_testdata |

- **Size:** 2870–3261 rows by 3580–4325 cols, 87.5–105.9 MB per sample.
  Total 977,705,000 bytes, which is 244,426,250 float32 values.

## Selection (`discover.sh` → `sources.tsv`)

`discover.py` builds the selection in these steps:

1. List the whole bucket prefix `sar-data/tasks/` anonymously: 40,178 keys,
   7,867 SICDs (median about 1.7 GB).
2. Take SICDs in ascending size order.
3. Range-probe the 4 KB head and 64 KB tail of each, and parse the NITF
   header, image subheader and SICD XML DES.
4. Keep only products in the regime above.
5. Skip repeat scenes: an SCP within 0.05° of an already selected product.
6. Stop before image bytes exceed 1e9.

Of the 24 smallest SICDs:

- 6 are excluded as processor 0.3.x (early `ship_detection_testdata`).
- 3 are excluded as 0.7.1.1 (Beet Piler, Sugar Beet plant, one NDSU collect).
- 4 are excluded as repeat scenes.
- 10 are selected.
- The 24th (Centerfield UT, 110 MB) would cross the cap.

The natural records are 60 MB to several GB, so the 1 GB cap limits the
recipe to about 10 whole images. No tiling is done.

## Pipeline

- `download.sh`
  - Uses curl with `-C -` and `--speed-limit 1024 --speed-time 120` into
    `.part` files, preceded by a one-byte liveness GET.
  - `recipe.py validate` then checks each file:
    - exact size
    - the S3 multipart ETag, recomputed with the pinned 8/16 MiB part size
      (confirmed per object via `HEAD ?partNumber=1`)
    - full NITF/SICD structure and regime assertions, plus agreement with
      the pinned offsets, geometry, collector and processor
    - finite, non-constant pixels; not zero-dominated (realized: no zeros at all)
- `build.sh` (`recipe.py build`) streams the image segment, applies
  `array('f').byteswap()` and writes `<collect>.f32`. Each index row carries:
  - shape `[rows, cols, 2]`
  - stored-dtype min/max and sha256
  - zero-pixel fractions overall, inside and outside the ValidData polygon
  - the residue / row-coherence diagnostic (see below)
  - processor, collector, polarization, SCP, sample spacing / IRW, grazing
    angle, source key and ETag
- `verify.sh` (`verify.py`) uses no shared code. It has its own
  fixed-offset NITF reader, regex XML parse and slice-based byte reversal.
  It:
  - byte-compares every sample
  - recomputes sha256, min/max, zero fractions and the residue diagnostic
  - enforces the missing-value policy and a distinct-value floor
  - checks the manifest totals and the 1e9 cap

## Outside the ValidData polygon: scene content plus a processor-leakage wedge

No pixel is fill or a sentinel. Not one of the 244,426,250 values is exactly
0.0, and `zero_pixel_fraction` is 0 in every sample. Every pixel is kept
unchanged, because the natural record is the whole SICD image as distributed.

The area outside `ImageData/ValidData` is 32–53% of each grid, and it is not
one population. Measured with the diagnostic below, it holds two kinds of
pixel:

1. **Full-strength scene content beside the polygon.** The median power of
   outside pixels above the residue threshold is −0.3 to −3.2 dB relative to
   the interior median (`outside_nonresidue_median_db`).
2. **A low-level processor-leakage wedge** at a median of −42.9 to −46.8 dB
   relative to the interior median (`residue_median_db`). Properties:
   - **Coverage:** 18.5–28.8% of all sampled pixels in 9 samples, and 43–54%
     of their outside pixels. In the Chesapeake Bay sample
     (2023-10-01-14-30-15_UMBRA-04) it is only 2.7% of all pixels and 8.5%
     of the outside area.
   - **Row coherence:** in 25 wedge blocks per sample (16 rows × 32 cols,
     scratch measurement), the median adjacent-row complex coherence is
     0.71–0.83, with a block phase step mostly near ±155–180°. Taparal's
     wedge reaches 0.996. Real interior scenes give about 0.21–0.26 on the
     oversampled grid.
   - **Reduced precision:** wedge values have a median of 15–16 significant
     mantissa bits, against 22 in the interior (counted from trailing zero
     bits of the 23-bit float32 mantissa).

The wedge is native Umbra 0.6.x image-formation output, not a recipe
artifact. It is lower-entropy material than the scene, and a compressor will
see it as such.

The earlier wording, "attenuated real content 3–12 dB below the inside", was
wrong: it averaged these two populations. It has been withdrawn.

### Residue diagnostic (in the index, recomputed by `verify.py`)

Definitions:

- **Grid:** every 7th row from row 0 and every 5th column from column 0.
- **Power:** P = I² + Q² per pixel, computed in float64 from the stored
  float32 values.
- **Interior:** columns between ceil(left) and floor(right) crossings of the
  ValidData polygon on that row.
- **M:** the upper median (`sorted[n//2]`) of sampled interior P.
- **Threshold:** 1e-3 · M (−30 dB).

Index fields:

| Field | Meaning | Realized range |
| --- | --- | --- |
| `residue_fraction` | sampled pixels below the threshold | 0.0274; 0.1847–0.2876 for the other 9 |
| `residue_outside_valid_fraction` | outside-polygon sampled pixels below it | 0.0853; 0.4274–0.5448 for the other 9 |
| `residue_inside_valid_fraction` | interior sampled pixels below it | 0.00066–0.00156 |
| `residue_median_db` | 10·log10(median residue P / M) | −46.79 to −42.85 |
| `outside_nonresidue_median_db` | the same for outside pixels at or above the threshold (build only) | −3.22 to −0.29 |
| `row_adjacent_coherence`, `row_adjacent_phase_deg` | \|Σ z[r,c]·conj(z[r+1,c])\| / Σ ½(\|z[r,c]\|² + \|z[r+1,c]\|²) and its angle, over the central 256 × 256 block (rows R/2−128 … R/2+127 against the next row) | 0.211–0.262 for 9 samples; 0.929 at 104° for Taparal |

`verify.py` recomputes the first four fields and the coherence with its own
`struct`-based reader and polygon code. It requires agreement within 1e-6 on
the fractions, 0.01 dB on the median and 1e-5 on the coherence. Build and
verify both fail if more than 1% of sampled interior pixels fall below the
threshold, which guards against hidden fill inside the valid area.

### Other rejection rules (build and verify)

A sample is rejected for any of:

- NaN or Inf anywhere
- a constant sample
- more than 5% exact-zero pixels inside the polygon
- fewer than 30% nonzero pixels
- (verify only) fewer than 100,000 distinct values

## License

The AWS Open Data registry YAML for `umbra-open-data` says: "All data is
provided with a Creative Commons License (CC by 4.0) …". The bucket is not
requester-pays. Attribute "Umbra Space, Umbra SAR Open Data".

## Caveats

- Only 10 samples, because the cap binds on 87–106 MB records.
- Complex pixel scale is uncalibrated and can differ between collects. It is
  the same quantity and processor family.
- Processor minor versions 0.6.1–0.6.6 are mixed; 0.3.x and 0.7.x are
  excluded.
- 4 of the 10 scenes come from Umbra's `ship_detection_testdata` folder. They
  are harbour or sea scenes; the others are land.
- 9 of 10 samples are 18–29% low-level leakage wedge (above). It is native
  and kept, but it is less informative than scene pixels.
- **Taparal, Colombia (2023-09-10-14-53-10_UMBRA-04):**
  - The whole image is dominated by a row-direction coherent component.
    Adjacent-row complex coherence is 0.929 on the central 256 × 256 block,
    against 0.21–0.26 for the other nine.
  - In 64-row bands from row 300 to row 2300 the coherence falls from 0.98
    to 0.87, and the phase step drifts from about 123° to 91°, top to bottom.
  - The sample also has the smallest amplitude range (|value| ≤ 0.17).
  - This fits narrowband interference over a low-backscatter rainforest
    scene. It is kept as a natural record of the 0.6.x product, and the
    index flags it through `row_adjacent_coherence`.
