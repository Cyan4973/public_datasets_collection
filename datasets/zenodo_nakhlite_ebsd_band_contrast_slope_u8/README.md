# Martian nakhlite EBSD Band Contrast / Band Slope maps (uint8)

This recipe collects per-scan-point EBSD pattern-quality rasters from Zenodo
record [5545821](https://doi.org/10.5281/zenodo.5545821) (Griffin et al.,
"Constraints on the emplacement of Martian nakhlite igneous rocks and their
source volcano from advanced micro-petrofabric analysis", CC BY 4.0). Each
`.ctf` file is one EBSD grid map of a nakhlite thin section. Every scan
point carries two native 8-bit integers computed by the Oxford HKL CHANNEL5
indexer:

- **BC (Band Contrast)**: the Hough-peak intensity of the detected Kikuchi
  bands relative to the pattern, scaled to 0-255.
- **BS (Band Slope)**: the sharpness of the band edges, scaled to 0-255.

Both are 0 where no pattern was solved (off-sample, epoxy, cracks, poorly
polished areas). Rendered as images, BC maps are the standard grain and
texture "quality maps" of EBSD work.

## Scope

There are two primary series. Each has one sample per map, a YCells x XCells
uint8 raster in raster order (row-major, scan x fastest).

| map_id | sample | grid (Y x X) | step (µm) | scan points | .ctf bytes |
|---|---|---|---|---|---|
| NWA998_UG1 | NWA 998 | 1091 x 1636 | 4.5 | 1,784,876 | 111,773,804 |
| NWA998_T1 | NWA 998 | 1037 x 1522 | 2.5 | 1,578,314 | 98,762,664 |
| Y749_72A | Y000749 | 2418 x 2294 | 3.0 | 5,546,892 | 343,735,226 |
| Y749_64A | Y000749 | 2007 x 2983 | 3.3 | 5,986,881 | 374,271,023 |
| Y593_127A | Y000593 | 1258 x 1736 | 3.3 | 2,183,888 | 139,963,789 |
| Y593_106A | Y000593 | 1787 x 2244 | 3.0 | 4,010,028 | 255,202,129 |
| Y802_36A | Y000802 | 1243 x 1154 | 5.0 | 1,434,422 | 91,115,880 |
| GV_BM1975M16P19783 | Governador Valadares | 236 x 396 | 15.0 | 93,456 | 6,138,014 |
| MIL_090136_50 | MIL 090136 | 1553 x 2322 | 3.46 | 3,606,066 | 222,209,866 |
| Lafayette_USNM1505-5_LAM | Lafayette | 1853 x 2481 | 4.0 | 4,597,293 | 291,951,528 |

That gives 30,822,116 values per series and 61,644,232 primary bytes over
20 samples. The download is 1,935,123,923 bytes of text plus the record JSON.
The median sample has about 2.9 M values. The smallest is GV at 93,456.

### Homogeneity and exclusions

All 10 maps are legacy CHANNEL5 exports. Their headers have an empty
`Author`, `Device 0`, 4-decimal steps, `KV 20.0000` (GV: 19.9950),
`TiltAngle 70.0000` and the same `DetectorOrientationE1` of about 359.4°.
They all come from one petrofabric study of one meteorite group. The rest of
the record is excluded as separate regimes:

- the 9 AZtec exports (`Author AZtec`, `Device 1`): different acquisition
  software and probably a different detector, so BC/BS are scaled
  differently;
- `NWA 817_N8-1_NR_crystal.ctf`: AZtec-style header, 0.4 µm step, tilt
  stored in radians, 2.96 GB;
- `Caleta El Cobre_ LAM_CERGE.ctf`: a terrestrial sample, AZtec, `Device 1`.

No maps are added to raise the sample count.

## Conversion

`.ctf` is a tab-separated text format with CRLF line endings. It starts with
`Channel Text File`, followed by key/value header lines, one line per phase,
and a column line `Phase X Y Bands Error Euler1 Euler2 Euler3 MAD BC BS`.
After that comes one row per scan point.
`scripts/build_ctf.py` streams each file line by line and never holds the
text in memory. It takes `XCells/YCells/XStep/YStep` from the header and
finds the X, Y, BC and BS positions by name. Each row goes to grid cell
`(round(Y/YStep), round(X/XStep))`. The int values of BC and BS are written
into two YCells*XCells byte buffers. A file is rejected, never repaired,
when it has:

- off-lattice coordinates, or duplicate or unfilled cells;
- a row count different from XCells*YCells, or the wrong field count;
- any BC/BS that is not a decimal integer in 0..255 (no clamping).

The files are written in raster order already (first and last rows checked),
so the placement is the identity. The build logs `out_of_order` per map.
Phase, X/Y, Bands, Error, Euler angles and MAD are not emitted.

## Integrity

- `download.sh` re-reads the live record and checks the title, `cc-by-4.0`,
  open access, and the size and md5 of all 10 files. It fetches each file
  whole with `curl -C -` and `--speed-limit 1024 --speed-time 120` (no
  `--max-time`) into `<map_id>.ctf.part`, with URL-encoded keys
  (`MIL%20090136_50.ctf`).
  `scripts/check_ctf_header.py` then checks:
  - pinned size and md5;
  - first line, empty Author, Device 0, KV 20, tilt 70, JobMode Grid;
  - the pinned grid and step, and exactly one Phase/X/Y/BC/BS column;
  - that the last row sits on the last grid cell.
- `verify.sh` (`scripts/verify_ctf.py`, which does not import the build)
  re-checks the md5s and re-derives both rasters with its own parser. It
  byte-compares every sample, checks the index fields, sha256 and
  min/max/distinct/zero share, and the manifest totals. It rejects samples
  with fewer than 16 distinct values or a zero share above 0.8, and prints
  the zero (unindexed) share of every sample.

Local disk: about 1.94 GB of downloads plus 62 MB of samples. The `.ctf`
files are kept so that verify can re-derive from them.

## Caveats

- There are only 10 maps per series, a limit set by keeping one homogeneous
  CHANNEL5 regime. The record has no other legacy maps.
- BC and BS come from the same scan points and are correlated. They are
  kept as two primary series of different quantities. The zlsim result
  should be read per series. If only one is wanted, BC is the main one.
- Unindexed points carry BC=BS=0. The realized zero share per map is
  1.3% (GV), 2.6% (Y802_36A), 5.3% (Lafayette), 9.4% (Y593_106A), 10.2%
  (Y749_64A), 10.5% (MIL 090136), 13.1% (NWA998_UG1), 18.0% (Y749_72A),
  18.9% (Y593_127A) and 19.7% (NWA998_T1). Mid-file probes during authoring
  had suggested about 28% for MIL 090136; the whole-map figure is 10.5%. The
  zero masks of BC and BS are identical pixel for pixel in all 10 maps. These
  zeros are genuine indexer output and are kept.
- BS in MIL 090136 only reaches 130 (94 distinct values), and BC in
  NWA998_T1 only reaches 212. Both reflect the acquisition and are not
  clipped.
