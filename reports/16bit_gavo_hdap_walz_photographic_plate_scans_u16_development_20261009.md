# HDAP Walz reflector lunar plate-scan uint16 development

## Outcome

Accepted `gavo_hdap_walz_photographic_plate_scans_u16`. It collects 25 complete digitized historic photographic glass plates of the Moon. The plates were exposed with the Heidelberg-Königstuhl 72 cm Walz reflector between 1906 and 1924 and scanned in 2011 for HDAP (Heidelberg Digitized Astronomical Plates). The GAVO Data Center serves them as native unsigned 16-bit FITS images.

This is the first photographic-plate family in the corpus. No GAVO, HDAP or plate/film-scan source exists locally, in the registry, in the ledger or downstream. It is labelled `new_source`, not `new_modality`, because 16-bit grayscale astronomical frames and scanner images already exist. zlsim measured it STRONG: the nearest family is downstream `air_o3` at distance 0.1324.

The scout's card proposed Walz star fields. Every Walz plate of 62 MB or less is lunar, though, and the star, comet and asteroid plates run 110-450 MB each. The recipe was therefore honestly narrowed to the lunar subset, and the manifest and README describe it as such.

## Source and rights

- Source: GAVO DC HDAP (`lsw.plates` via TAP); files from `http://dc.g-vo.org/getproduct/lswscans/data/part2/Walz/FITS/<plate>.fits` (server Last-Modified 2013-08-01)
- License: CC0-1.0. The VOResource record for `ivo://org.gavo.dc/lswscans/res/positions/siap` carries `<rights rightsURI="https://spdx.org/licenses/CC0-1.0.html">To the extent possible under law, the publisher has waived all copyright and related or neighboring rights to the HDAP scans.`
- The record's description states that HDAP is essentially complete for the Walz reflector plates, so the waiver covers these exact FITS objects. An acknowledgement is requested and recorded in the manifest citation.
- Pins: per plate URL, size (`accsize`, equal to the Content-Range total), NAXIS1/2 and the SHA-256 of the 5,760-byte header. Upstream publishes no file checksum, so full-file SHA-256s are frozen in `download_plan.tsv` at download.

## Shape and conversion

Each natural record is one complete plate scan: the FITS primary HDU, BITPIX 16, NAXIS 2, BZERO 32768, BSCALE 1, no BLANK. File size equals header + data + padding exactly, so there are no extension HDUs. The big-endian int16 values get +32768 (a sign-bit flip) and are written as little-endian uint16 in FITS order, one sample per plate, with no cropping, tiling or scaling. Header text is not emitted.

Values increase with emulsion density, so the lunar disks are bright. The scanner applied a tone curve that leaves about 2,800-3,700 sparse codes per plate. There are six session-specific curve lattices, which line up with the 2011 scan dates. All share the same structure: floor 1422, then about 2,985, steps of 12-26 DN, top 65535.

Selection (`scripts/discover.py`) takes 25 of the 43 lunar plates of 62 MB or less:

- all plates of the sparse seasons: S1 1906/07 (3), S4 1918 (3), S5 1920 eclipse (1) and S6 1924 (3)
- 7 of 15 plates from S2 (March-April 1907) and 8 of 18 from S3 (1909), at evenly spaced date ranks

## Dominant value (fill warning)

Code 1422 is the clip floor of the scanner tone curve. It is the minimum of every plate, isolated from the rest of the curve, and covers unexposed clear glass around the lunar disks.

| Measure | Value |
|---|---|
| Share of all values | 40.7% |
| Plates where it is above 50% | 6 (D78 0.70, D81 0.62, D83 0.62, D86 0.59, D105 0.86, D494 0.51) |
| Plates where it is below 1% (sky fog above the floor) | 6 |
| zlsim mode_share | 0.859 (D105) |

1422 is a genuine clipped measurement inherent to lunar plates, not fill or no-data, and the plates were pinned without looking at the pixel data. The precedent is the return-number u8 acceptance, where a dominant genuine measurement was kept. Non-floor content remains about 263 M values (about 526 MB).

## Accepted output

| Measure | Value |
|---|---|
| Primary samples | 25 (seasons S1 3, S2 7, S3 8, S4 3, S5 1, S6 3) |
| Primary values | 443,106,625 |
| Primary bytes | 886,213,250 |
| Downloaded bytes | 886,386,240 |
| Minimum sample | 10,544,880 values (D482, 4145x2544) |
| Median sample | 15,998,398 values |
| Maximum sample | 30,888,489 values (D105, 7057x4377) |
| Distinct codes per plate | 2,812-3,695 |
| Zeros | 0 |
| Pixels at 65535 | 92, across 15 plates |
| Non-zero padding bytes | 0 |

Aggregate SHA-256 of the sample hashes in pinned order: `5f2f6ce7029c445d71707292082df566e6ae7f0fc6f25b7ef9e155f173f25d90`

## Judge checks

- `gate.py`: PASS, no warnings.
- `verify.sh`: re-run by the judge (33 s). Passed: a separate header reader, byte comparison of all samples against an array-byteswap decode, struct arithmetic on every 97th row, recomputed statistics and manifest totals.
- `build.sh`: local-only (selftest plus `build.py`); `download.sh` logged `license_check=ok`.
- Decode spot check: my own struct code matched signed BE int16 + 32768 to the stored LE uint16 on 2,000 random pixels in each of D78, D41, D2050 and D482.
- Coarse maps of D78, D105, D41 and D2050 show real lunar double exposures with emulsion grain. Mean absolute row deltas run from 178 to 3,234 DN. There are no duplicates. Same-night plates are distinct physical plates with different shapes.
- Code-set clustering found six tone-curve lattices of identical structure. The intersection of all 25 code sets is only {1422}. This is judged homogeneous: one unit and range, one campaign.
- Rights: I fetched the live OAI record and confirmed the CC0 element and the Walz coverage. The hash drift comes from `responseDate`. No credentials in any script; no personal data emitted.
- A TAP probe confirmed the population: 46 lunar Walz plates (1.91 GB); 43 at 62 MB or less (1.56 GB); no non-lunar Walz plate at 62 MB or less; 4,035 Walz plates in total.
- Novelty: `novelty.py` URL, terms, type, instrument and archive queries found no comparable family.
- Minor documentation imprecision, not blocking:
  - The manifest says "most plates carry two 1 s exposures"; the header REMARKS give 1 s on 13 of 25 plates and 0.1-1.4 s on the rest.
  - The builder summary's "only D55 saturated" is wrong (92 pixels at 65535 across 15 plates), but the recipe docs make no such claim.
