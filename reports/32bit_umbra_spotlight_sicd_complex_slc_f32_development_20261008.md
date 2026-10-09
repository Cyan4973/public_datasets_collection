# Umbra spotlight SICD complex SLC float32 development

## Outcome

Accepted `umbra_spotlight_sicd_complex_slc_f32` after one repair cycle. The repair was documentation and diagnostics only; the samples did not change.

This is the corpus's first phase-preserving complex SAR material. The SAR families already accepted hold detected backscatter amplitude:
- Magellan F-MIDR u8
- Cassini BIDR sigma0 u8
- Sentinel-1 GRD u16

The accepted complex float32 I/Q families come from other modalities:
- LoRaIQ RF baseband
- EHT visibilities

The novelty is therefore a new quantity in a known modality (`new_quantity`). The driver's measured breadth verdict is OK: the nearest family is gencast GNN weights at a feature distance of 0.053.

## Source and rights

- **Source:** the Umbra Open Data Program, AWS Open Data bucket `umbra-open-data-catalog` (us-west-2, not requester-pays), accessed by anonymous HTTPS GET.
- **Objects:** 10 pinned `*_SICD.nitf` objects, 978,017,309 bytes in total. `sources.tsv` (sha256 `e02652108f7fcb144a62b9c3e00cd516d72a9179eb99df8ea8fb5e261eacb291`) pins each object's:
  - key and size
  - multipart ETag and part size
  - NITF offsets
  - geometry
  - collector and processor
- **License:** CC BY 4.0. The AWS open-data-registry `umbra-open-data.yaml` says: "All data is provided with a Creative Commons License (CC by 4.0)". It names the bucket resource "Umbra Spotlight collects including GEC, SICD, SIDD, CPHD data and metadata". umbra.space/open-data repeats the Creative Commons grant.
- **Attribution:** Umbra Space, Umbra SAR Open Data.

## Shape and conversion

Each natural record is one whole SICD product, the complete complex image of a single collect.

The recipe parses and asserts the following:

| Layer | What is checked |
| --- | --- |
| NITF 2.1 file header | NUMI 1, NUMDES 1 |
| Image subheader | PVTYPE R, ABPP/NBPP 32, IC NC, NBANDS 2 with ISUBCAT I and Q, IMODE P, a single block, no LUTs |
| SICD 1.2.1 XML DES | RE32F_IM32F, SPOTLIGHT, MONOSTATIC, PFA, RGAZIM, full image, X band, "Umbra Image Formation processor 0.6.x" |

The image segment is the only thing emitted. Its big-endian float32 values are byteswapped to little-endian, written row-major `[row][col][I,Q]`, and left otherwise untouched: no crop, tile, scale or calibration. Headers and XML stay in the downloads.

**Selection.** Products are taken in ascending size order. A product is kept only if it conforms to the regime and its scene centre point (SCP) is at least 0.05° from every product already kept. Selection stops at the 1e9-byte cap:
- Of the 24 smallest SICDs, 6 are excluded as processor 0.3.x, 3 as 0.7.1.1 and 4 as repeat scenes.
- The 24th product (Centerfield UT, 110 MB) would cross the cap.

The selected scenes:
- Chesapeake Bay
- Tanna Island
- Strait of Hormuz
- Purdue farm plot
- Manzanillo
- Taparal
- NDSU plot
- Magui Payan
- Myra ND
- offshore Angola

**Outside the ValidData polygon.** This area is 31-53% of each grid. It holds two populations:
1. Full-strength scene content beside the polygon, median −0.3 to −3.2 dB relative to the interior median power.
2. A native low-level wedge left by the Umbra 0.6.x processor, median −42.9 to −46.8 dB. It is row-coherent and carries 15-16 significant mantissa bits, against 22 in the interior. It covers 18.5-28.8% of pixels in 9 samples and 2.7% in Chesapeake.

The wedge has no sentinel and contains no zeros. It is kept because the natural record is the whole image.

**Taparal (2023-09-10-14-53-10_UMBRA-04).** This sample is dominated by a row-coherent, interference-like component: central-block coherence is 0.929, against 0.21-0.26 elsewhere. It is documented and flagged in the index.

## Accepted output

| Measure | Value |
| --- | --- |
| Primary samples | 10 |
| Primary values | 244,426,250 float32 (122,213,125 complex pixels) |
| Primary bytes | 977,705,000 (99.97% of downloaded bytes) |
| Minimum sample | 21,873,800 values (87,495,200 B; Chesapeake Bay, 3055 x 3580) |
| Median sample | 24,983,780 values |
| Maximum sample | 26,469,000 values (105,876,000 B; offshore Angola, 3060 x 4325) |
| Exact zeros, NaN, Inf | none |
| Interior residue fraction | 0.066-0.156% (guard: 1%) |
| Processors | 0.6.1.2 (6 samples), 0.6.2.0, 0.6.4.1, 0.6.6.0 (2 samples) |
| Collectors | Umbra-04 (3), Umbra-05 (5), Umbra-06 (2) |

**Index fields per sample:**
- shape, stored-dtype min/max, sha256
- zero fractions inside and outside the polygon
- residue fraction (overall, outside, inside), residue median dB, outside non-residue median dB
- row-adjacent coherence and phase
- collect, site, collector, processor, polarization, SCP, sample spacing, impulse-response width, grazing angle
- source key, ETag and size

**Caveats:**
- Only 10 samples: the cap binds on records of at least 87 MB, and tiling is not allowed.
- The per-collect pixel scale is uncalibrated.
- About a quarter of the pixels in 9 samples are the low-information wedge.
- The Taparal sample is interference-dominated.
- Four of the scenes are sea or harbour; six are land.

## Judge checks

- **Gate:** `python3 tools/autocollect/gate.py staging/umbra_spotlight_sicd_complex_slc_f32` passes with no warnings.
- **verify.sh:** I ran it myself; exit 0 in 19.6 s. It is independent of the build code: its own NITF reader and byte reversal, a byte-compare, and recomputation of sha256, min/max, zero fractions, residue fractions and median dB, and coherence.
- **Pinned plan:** sha256(sources.tsv) matches the manifest.
- **No network in build or verify:** curl appears only in `download.sh` and in the metadata-only `discover.py`.
- **Download validation:** the driver's download log shows 10/10 files passing size, multipart ETag and structure checks.
- **Byteswap:** for every sample, an independent struct read of the big-endian NITF image segment equals the little-endian sample at 4 rows.
- **Distributions:** I and Q are zero-mean with sd 0.008-0.044. Kurtosis is 5-18 on land and very high on ship scenes. Exponents span 2^-29 to 2^1, with 22 significant mantissa bits in the interior, so the full float32 width is genuinely used.
- **Duplicates:** hashing every row of all samples found no duplicate rows within or across samples.
- **Wedge:** ASCII power maps show the PFA rotated footprint with low-level corner triangles. At full column resolution the residue fraction matches the index within 0.5 percentage points. My own wedge coherence is 0.75-0.85 (Taparal 0.999), with 15-16 vs 22 significant mantissa bits, which agrees with the README.
- **Homogeneity:** the SICD XML of all 10 products shows one chain: Valkyrie Sage / Umbra IFP 0.6.x, SLANT/RGAZIM, no beam compensation, no autofocus, 9.55 GHz, 91-108 MHz bandwidth.
- **Rights:** I fetched the AWS registry YAML (CC BY 4.0, names SICD, RequesterPays False) and umbra.space/open-data. The `ship_detection_testdata` prefix holds no separate terms.
- **Novelty:** `novelty.py` URL/terms and type/instrument/archive queries give no local or downstream complex-SAR match. The vocabulary shows only detected SAR and non-SAR complex I/Q. The driver's zlsim gives OK at 0.053.
- **Non-blocking:** the docs say the outside-polygon share is "32-53%"; the realized figure is 31.4-52.6%.
