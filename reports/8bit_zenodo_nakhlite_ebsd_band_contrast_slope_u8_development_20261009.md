# Nakhlite EBSD band contrast / band slope uint8 development

## Outcome

Accepted `zenodo_nakhlite_ebsd_band_contrast_slope_u8` from Zenodo record 5545821 (Griffin et al. 2021). It is the first EBSD indexing-quality map family in the corpus.

The local corpus already has `zenodo_nordif_ebsd_kikuchi_patterns_u8` and `zenodo_silicon_diffraction_tiff_u16`, and downstream has `silicon_ebsd_detector_u16`. All three hold raw Kikuchi detector frames. This recipe keeps something different: the scalar pattern-quality measures that the Oxford HKL CHANNEL5 indexer computes at each scan point.
- **Band Contrast (BC):** Hough-peak band intensity relative to the pattern, 0–255.
- **Band Slope (BS):** band-edge sharpness, 0–255.

Each map's BC and BS are kept as 2-D rasters of the scanned thin section.

## Source and rights

- **Source:** Zenodo record 5545821, DOI 10.5281/zenodo.5545821, published 2021-09-29. Title: "Constraints on the emplacement of Martian nakhlite igneous rocks and their source volcano from advanced micro-petrofabric analysis".
- **License:** CC BY 4.0. The record-level `license.id` is `cc-by-4.0` and `access_right` is `open`. The record description names the deposit as "Martian nakhlite meteorite electron backscatter data and magma body unit thickness calculation code". The `.ctf` files are the deposited data objects.
- **Files used:** the 10 legacy CHANNEL5 `.ctf` maps, 1,935,123,923 bytes in total. Their sizes and md5s are pinned in `maps.tsv`, and `download.sh` re-checks them against the live API.
- **Excluded:**
  - the 9 AZtec exports (`Author AZtec`, `Device 1`);
  - `NWA 817_N8-1_NR_crystal.ctf` (AZtec-style header, 0.4 µm step, 2.96 GB);
  - the terrestrial `Caleta El Cobre_ LAM_CERGE.ctf`;
  - the two MATLAB `.mlx` scripts.
- **Safety:** instrument data of meteorite thin sections, with no personal data.

## Shape and conversion

Each natural record is one EBSD grid map, i.e. one `.ctf` file. Every scan point is a tab-separated row: `Phase X Y Bands Error Euler1 Euler2 Euler3 MAD BC BS`.

`scripts/build_ctf.py` streams each file line by line. It takes `XCells/YCells/XStep/YStep` from the header and finds the X, Y, BC and BS columns by name. Each row is placed at cell `(round(Y/YStep), round(X/XStep))` of a YCells × XCells uint8 buffer, row-major with x fastest. BC and BS are written exactly as stored.

A file fails the build on any of the following; nothing is clamped or imputed:
- an off-lattice coordinate;
- a duplicate or missing cell;
- a row count different from XCells·YCells;
- a wrong field count;
- a non-integer value or a value above 255.

All 10 files are already in raster order (`out_of_order=0`).

Zeros are kept as stored. In the source, every BC=0 point also has BS=0, Bands=0 and Error=5 (CHANNEL5 "not analysed"). Most unindexed Phase-0 points still carry a nonzero BC. The zeros form contiguous off-sample blocks, about one run per row with a mean run of 140–380 pixels.

The manifest describes the zeros as "non-indexed or off-sample points". The accurate wording is "not-analysed (Error=5) points, which lie in off-sample regions". This is a documentation nuance only and does not affect the bytes.

## Accepted output

There are two primary series, each with 10 samples and 30,822,116 bytes:
- `ebsd_band_contrast_u8`
- `ebsd_band_slope_u8`

| map_id | grid (Y×X) | step µm | values | zero share | BC max / distinct | BS max / distinct |
|---|---|---|---|---|---|---|
| NWA998_UG1 | 1091×1636 | 4.5 | 1,784,876 | 0.1309 | 255 / 242 | 255 / 222 |
| NWA998_T1 | 1037×1522 | 2.5 | 1,578,314 | 0.1972 | 212 / 182 | 228 / 144 |
| Y749_72A | 2418×2294 | 3.0 | 5,546,892 | 0.1797 | 255 / 238 | 255 / 230 |
| Y749_64A | 2007×2983 | 3.3 | 5,986,881 | 0.1021 | 255 / 217 | 255 / 220 |
| Y593_127A | 1258×1736 | 3.3 | 2,183,888 | 0.1887 | 254 / 212 | 255 / 212 |
| Y593_106A | 1787×2244 | 3.0 | 4,010,028 | 0.0938 | 255 / 241 | 255 / 227 |
| Y802_36A | 1243×1154 | 5.0 | 1,434,422 | 0.0258 | 251 / 202 | 255 / 203 |
| GV_BM1975M16P19783 | 236×396 | 15.0 | 93,456 | 0.0126 | 255 / 233 | 255 / 212 |
| MIL_090136_50 | 1553×2322 | 3.46 | 3,606,066 | 0.1053 | 223 / 211 | 130 / 94 |
| Lafayette_USNM1505-5_LAM | 1853×2481 | 4.0 | 4,597,293 | 0.0535 | 227 / 202 | 237 / 170 |

- Primary samples: 20 (10 per series)
- Primary values and bytes: 61,644,232
- Minimum sample: 93,456 values
- Median sample: 2,894,977 values
- Maximum sample: 5,986,881 values
- Aggregate decoded SHA-256 (verify): `b13d797f0ef5f7c3096dafa3d04db3e5a2fae7e3825c4f241a8c160db77b5ce6`
- Download: 1,935,123,923 bytes of `.ctf` text plus the record JSON (about 3.2% extraction; text is the only form in the record)

## Judge checks

- **Gate:** `gate.py` PASS with no warnings (61,644,232 values, 20 samples, median 2,894,977, width 8).
- **Verify:** I ran `verify.sh` myself and got `verify_status=ok` in 49.7 s. It uses an independent parser that does not import the build, re-checks the md5s, byte-compares all 20 rasters, and checks the index and manifest totals. build.sh and verify.sh use local files only: neither they nor their Python scripts contain curl, wget or http.
- **Rights:** I fetched the live Zenodo API myself: `cc-by-4.0`, `open`. All 10 keys match the sizes and md5s in `maps.tsv`. No credentials in any script.
- **Bytes:** stdlib inspection of all 20 samples.
  - Nonzero BC means are 48–119 and BS means 50–96. The top nonzero value is at most 6.2% of a map.
  - Delta entropy in x and y is equal and below order-0, which confirms the stride and real 2-D structure.
  - zlib/lzma ratios are 0.49–0.81.
  - BC vs BS correlation on nonzero pixels is 0.79–0.95, with H(BS|BC) of 3.8–4.9 bits. BS is a distinct measurement, not a remap of BC.
- **Source rows:** I parsed the raw rows of GV, NWA998_T1 and Y802_36A. BC=0 coincides exactly with Bands=0 and Error=5. Zero runs confirm contiguous off-sample blocks.
- **Homogeneity:**
  - All 10 headers are CHANNEL5 Device 0 at 20 kV and 70° tilt; 9 share an identical detector orientation and GV differs slightly.
  - A 2 KB range probe of `Nakhla_WAM12965_crystal.ctf` confirmed `Author AZtec` / `Device 1` for the excluded set.
- **Novelty:**
  - `novelty.py` finds no URL match except the candidate itself.
  - The only EBSD hits are raw Kikuchi pattern families.
  - No existing family has the same measurement type or instrument line.
- **Breadth:** zlsim OK. BC is 0.0751 and BS 0.0721 from downstream `met_painting_rgb_plane_u8`. Compression loss is about 0, but the feature distance is above the 0.05 redundancy threshold.
- **Scope caveat:** 10 maps per series is the whole homogeneous CHANNEL5 population of this record. Each sample is multi-megabyte, so this is source-limited, not floor-sized.
