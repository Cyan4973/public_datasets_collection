# gwosc_o3b_h1_bulk_strain_f64

Calibrated LIGO Hanford (H1) gravitational-wave strain h(t) from the GWOSC
O3b bulk archive (`O3b_4KHZ_R1`, channel `H1:DCS-CALIB_STRAIN_CLEAN_SUB60HZ_C01`,
frame type `H1_HOFT_CLEAN_SUB60HZ_C01`, 4096 Hz), in native float64. One sample
is one complete 4096-s archive file: 16,777,216 values, 134,217,728 bytes.

- Source: https://gwosc.org/data/ , API v2 `https://gwosc.org/api/v2/runs/O3b`
  (O3b, GPS 1256655618-1269363618, DOI 10.7935/pr1e-j706)
- License: CC BY 4.0. https://gwosc.org/acknowledgement/ says "Data from this
  web site are licensed under a Creative Commons Attribution 4.0 International
  License", and every gwosc.org footer says "Data released under a CC BY 4.0
  License". Cite ApJS 267, 29 (2023) and include the GWOSC acknowledgment.
- Scope: 7 files, 117,440,512 values, 939,524,096 bytes, from 906,496,481
  downloaded bytes.

## Selection (`discover.sh`, author time)

`discover.sh` fetches the `H1_DATA` segment list of `O3b_4KHZ_R1` and splits
the O3b GPS span into 7 equal bins. In each bin it takes the 4096-s archive
slot nearest the bin centre that lies wholly inside one `H1_DATA` segment
(GWOSC files start at multiples of 4096 s). It keeps the slot only if GWOSC's
per-file detail document reports `dutycycle_percent` 100 and `nans_fraction`
0. The result is pinned in `files.tsv`: GPS start, URL, exact size, covering
segment, and GWOSC's published min/max/mean/stdev strain and BNS range.

| GPS start | UTC start | bytes |
|---|---|---|
| 1257562112 | 2019-11-12T02:48:14 | 130,442,356 |
| 1259376640 | 2019-12-03T02:50:22 | 129,721,100 |
| 1261191168 | 2019-12-24T02:52:30 | 129,775,341 |
| 1263005696 | 2020-01-14T02:54:38 | 129,634,903 |
| 1264824320 | 2020-02-04T04:05:02 | 129,023,362 |
| 1266638848 | 2020-02-25T04:07:10 | 128,967,559 |
| 1268449280 | 2020-03-17T03:01:02 | 128,931,860 |

Homogeneity: one detector, one run, one calibration and cleaning version
(C01, CLEAN_SUB60HZ), one sample rate and one unit. L1, V1 and the 16 kHz
release are deliberately excluded because they have different noise spectra
or sampling. Hardware continuous-wave injections, which are always on in O3,
are part of the published data and are kept (`Injmask` bit `NO_CW_HW_INJ` is
clear).

## Decode

`scripts/gwosc_h5.py` is a pure-stdlib HDF5 reader. It is derived from the
accepted SXS recipe's `sxs_h5.py` (superblock v0, v1 object headers,
symbol-table groups, v1 chunk B-trees) and adds two things the GWOSC files
need, both confirmed on real files:

- the `[deflate(level 1), fletcher32]` filter pipeline. The trailing
  little-endian Fletcher-32 of every stored chunk is verified, then the chunk
  is inflated;
- variable-length UTF-8 string scalars in a global heap (`/meta/*`).

`/strain/Strain` has 2048 chunks of 8192 values. Each sample is the
concatenation of the inflated chunks in element order, which is exactly the
dataset's logical float64 LE bytes.

`scripts/selftest_gwosc_h5.py` runs before download and build. It builds
synthetic GWOSC-layout files (global heap strings, out-of-order chunks,
two-level chunk B-tree, checksums written by a literal port of HDF5's
`H5_checksum_fletcher32`), decodes them byte-exact, and checks that each
corruption is rejected for its own reason: bad checksum, wrong channel,
missing DQ bit, NaN, inf, all-zero chunk, repeated chunk, GWOSC stats
mismatch, GPS mismatch, size mismatch, short strain, superblock v2.

## Checks (identical in download, build and verify)

The checks are: exact size; meta `StrainChannel`, `Detector`, `FrameType`,
`Type`, `GPSstart`, `Duration`; strain shape, dtype, filters and chunking; the
`Npoints`, `Xspacing` and `Xstart` attributes; DQ `DATA` bit set in all 4096
seconds; per-chunk Fletcher-32; finite values with no all-zero or repeated
chunk; min/max equal to GWOSC's published values (relative 1e-9) and stdev
within 1e-3. GWOSC publishes no file checksums, so `download.sh` records the
observed sha256 (`SHA256SUMS`), and the sha256 of each file observed on the
first full download (2026-10-09) is pinned in the `sha256` column of
`files.tsv`. Download, build and verify all enforce the pinned value. `verify.sh` additionally scans
the stored samples independently, byte-compares each against a fresh decode,
and checks the index and manifest totals.

## Known risks

- Only 7 samples. This is forced by 134 MB natural records under the 1 GB cap,
  and the records are not split. Downstream sub-samples about 100 MB per
  family anyway.
- Byte-level similarity: strain is low-frequency-dominated colored noise and
  may sit near smooth f64 families in zlsim. This has not been measured yet.
- The GWOSC stats check assumes the published per-file min/max were computed
  from these exact 4 kHz files. If it fails on real data, the log shows both
  values.
