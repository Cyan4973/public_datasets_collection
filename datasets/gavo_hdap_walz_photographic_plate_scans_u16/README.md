# HDAP Walz Reflector Lunar Glass-Plate Scans (uint16)

25 complete digitized photographic glass plates of the Moon, exposed between 1906 and 1924
with the 72 cm Walz reflector at Heidelberg-Königstuhl (most plates hold two 1 s exposures)
and scanned for HDAP (Heidelberg Digitized Astronomical Plates). The GAVO Data Center serves
each plate as a FITS primary image (BITPIX 16, BZERO 32768), i.e. native unsigned 16-bit
scanner gray values. Each plate becomes one row-major little-endian uint16 sample.

- Source: https://dc.g-vo.org/lswscans/res/positions/siap/info (TAP table `lsw.plates`)
- License: CC0-1.0. The HDAP VOResource record carries
  `<rights rightsURI="https://spdx.org/licenses/CC0-1.0.html">To the extent possible under law, the publisher has waived all copyright and related or neighboring rights to the HDAP scans ...`.
  The service also asks for this acknowledgement: "This work made use of the HDAP which was produced at
  Landessternwarte Heidelberg-Königstuhl under grant No. 00.071.2005 of the Klaus-Tschira-Foundation."
- Scope: 25 plates, 443,106,625 values, 886,213,250 primary bytes (886,386,240 bytes downloaded).

## Why only lunar plates

The archive holds 4,035 Walz plates. Almost all of them are star, comet or asteroid fields
of 110-450 MB each, so only 2-8 of them would fit under the cap. All 46 Walz plates
catalogued as `Moon` / `Moon (Eclipse)` are 21-147 MB, and every Walz plate under 62 MB is
lunar. So this family is one subject (the Moon) through one telescope, one plate archive,
one scanning campaign (2011) and one storage convention. Bruce astrograph, Doppelastrograph,
Calar Alto and non-lunar Walz plates are excluded.

## Selection (scripts/discover.py, pinned in sources.tsv)

Of the 46 lunar plates, 43 are at most 62 MB (D59, D60 and D61 are 75-147 MB). Grouped by
observing season:

| season | span | eligible | pinned |
|---|---|---|---|
| S1 | 1906-12 to 1907-01 | 3 | 3 (all) |
| S2 | 1907-03 to 1907-04 | 15 | 7 (even date ranks) |
| S3 | 1909-01 to 1909-04 | 18 | 8 (even date ranks) |
| S4 | 1918-01 | 3 | 3 (all) |
| S5 | 1920-05 (catalogued "Moon (Eclipse)") | 1 | 1 |
| S6 | 1924-12 | 3 | 3 (all) |

Plates are 4145-7065 columns by 2534-4377 rows (21-62 MB). Per plate, `sources.tsv` pins
the URL, size (`lsw.plates.accsize`, equal to the server's Content-Range total), NAXIS1/2,
header length, the SHA-256 of the 5,760-byte primary header (taken from a Range probe),
DATE-OBS and the season. Upstream publishes no file checksum, so `download.sh` writes the
full-file SHA-256 to `downloads/<id>/download_plan.tsv`, and build and verify require it.
`discover.sh` re-runs the TAP query and the header probes and diffs the result against
`sources.tsv`.

## Conversion

The primary header (two 2,880-byte blocks) is followed by NAXIS1*NAXIS2 big-endian int16
values. Adding BZERO = 32768 (that is, flipping bit 15) gives the archived uint16, which is
written little-endian in FITS order (column fastest). There is no cropping, tiling, scaling or masking.
Each file is exactly header + data + padding, so no extension HDU exists, even though
`EXTEND = T` is declared.

The archived values use a sparse, non-uniform code set (about 3,400 distinct codes in a
1 M-pixel probe of D482, with typical gaps of 10-22 DN between 47,000 and 58,000), which
looks like a scanner tone curve. The full build finds 2,812-3,695 distinct codes per plate.
Values increase with emulsion density: the two dense lunar disks of each double exposure are
bright.

## Dominant value: clipped clear glass (code 1422)

Code 1422 is the floor of the tone curve. On most plates the unexposed clear glass around
the lunar disks, together with the scanner border, is clipped to it. This was measured
after the download, on the selection pinned before any data was seen:

| floor_1422_fraction | plates |
|---|---|
| < 0.01 | D41, D53, D55, D443, D2050, D2835 (sky fog sits above the floor; there the dominant value covers 0.2-1.6%) |
| 0.2-0.5 | D30, D35, D470, D473, D482, D485, D487, D491, D1625, D1626, D1627, D2834, D2836 |
| 0.5-0.86 | D78 (0.70), D81 (0.62), D83 (0.62), D86 (0.59), D105 (0.86), D494 (0.51) |

Across all values the floor fraction is 40.7%. It is a real measurement (clipped clear
glass), not a fill value, and it is kept. The larger-format March-April 1907 plates
(D78-D105) are the most clipped. `build.py` writes `dominant_value`, `dominant_fraction`
and `floor_1422_fraction` per plate to the index. Build and verify fail only if one value
covers more than 90% of a plate, which would be an essentially blank scan.

Probes of four Walz star-field plates (D98, D411, D1702, D2599; 200 mid-plate rows each)
found 0.7-1.5% at 1422 on three of them and 49% on D1702. Those plates are 140-158 MB
each, so only about 6 fit under the cap. That is why the recipe stays with the lunar subset.

## Scripts

- `download.sh`: CC0 record check, then a resumable curl per plate (`-C -`, retries,
  `--speed-limit 1024 --speed-time 120`, no `--max-time`), then the header regime,
  header hash and size checks (`scripts/fitsplate.py check-file`), then the download plan.
- `build.sh`: `scripts/selftest.py` (synthetic FITS: both parsers, both decoders, regime
  rejections), then `scripts/build.py`.
- `verify.sh`: `scripts/verify.py`, with an independent header reader, a different decode path
  (array byteswap + XOR, plus exact struct arithmetic on every 97th row), a full byte comparison,
  recomputed statistics, and checks of index, pins, plan and manifest totals.

## Caveats

- Only 25 samples. The lunar population is 46 plates, and the cap limits how many fit.
- About 41% of all values are the clipped clear-glass floor (see above).
- Season S2 and S3 plates from the same night are near-repeat exposures of the same lunar
  phase. Even-rank sampling spreads the picks, but some pinned plates share a night.
- D2050 is catalogued "Moon (Eclipse)". Its header metadata (UT 12:34, EXPTIME 1.0)
  looks like a placeholder, like the other lunar plates. It is kept as the only 1920 plate.
- Header times and exposure (EXPTIME = 1.0) of lunar plates are catalogue placeholders.
  Neither is emitted.
