# mast_jwst_nirspec_g395h_tso_x1dints_flux_f64

Per-integration extracted 1-D spectra from JWST NIRSpec bright-object time
series (BOTS). Each sample is the complete `FLUX` column of the `EXTRACT1D`
table of one Level-2 `*-seg001_nrs1_x1dints.fits` product: one row per
integration, about 1,272 wavelength bins per row (≈2.87–3.72 µm on detector
NRS1), native float64 in Jy. The samples are converted from FITS big-endian
to little-endian and are otherwise untouched.

- 66 samples, one per target, from 45 programs, observed 2022-05 to 2026-07
- 49,094 integrations, 62,455,583 values, 499,644,664 bytes, as pinned at
  discovery
- rows per sample: 8 to 1,462. Values per sample: 10,168 to 1,861,126
  (median 886,584)

## Source and rights

- MAST (STScI). Discovery uses `Mast.Caom.Filtered` / `Mast.Caom.Products`
  at `https://mast.stsci.edu/api/v0/invoke`. Data are read from
  `https://mast.stsci.edu/api/v0.1/Download/file?uri=mast:JWST/product/<file>`.
  Access is anonymous.
- Rights: MAST Data Use Policy
  (<https://archive.stsci.edu/publishing/data-use>): "Most data hosted at
  MAST are in the public domain … and therefore do not have restrictions on
  use." The restricted subsets are exclusive-access data, HLSPs (CC BY) and
  DSS/GSC. MAST reports `dataRights = PUBLIC` for every selected observation
  and file, and the 15 exclusive-access observations of this mode are
  excluded. `download.sh` re-checks the policy page.
- Acknowledge JWST/NIRSpec, MAST/STScI and the programs in `sources.tsv`.

## Selection (`discover.sh`, `scripts/discover.py`, pinned in `sources.tsv`)

1. `Caom.Filtered` with JWST, `timeseries`, `NIRSPEC/SLIT`, `F290LP;G395H`
   and calib_level 3 returned 140 observations: 125 PUBLIC and 15
   EXCLUSIVE_ACCESS. Of the public ones, 122 are SUB2048 and 3 are SUB1024B;
   the SUB1024B ones are excluded so that a single subarray is used.
2. `Caom.Products` for the 122 observations listed 128 public
   `*-seg001_nrs1_x1dints.fits` products.
3. A sparse header walk read 57,600-byte HTTP range pieces until the
   `EXTRACT1D` header, for all 128 products (≈14 MB in total). Every product
   passed the regime below.
4. One product per target. Target names are normalised, so `L98-59`,
   `L-98-59` and `L98-59-updated` count as one target. Ties go first to the
   newest `CAL_VER`, then to the lowest file name. This gives 70 targets.
5. The four largest products were then dropped to keep FLUX bytes at or
   below 500 MB, leaving 66 products.

Discovery found that MAST is reprocessing these products in place to
`CAL_VER 3.0.0` / `jwst_1584.pmap` / SDP `2026_2a`. 68 of the 128 candidates
had already been reprocessed, and 12 of them were served at a size that
differed from their Caom catalogue listing. The served size is
authoritative. The selection has 42 products at 3.0.0 and 24 at 2.0.1 / `jwst_1535.pmap` /
`2026_1b`. Each row in `sources.tsv` pins:
- ETag, served size and Last-Modified
- CAL_VER, CRDS_CTX and SDP_VER
- NINTS, INTSTART and INTEND
- the EXTRACT1D data offset, NAXIS1 and NAXIS2
- the FLUX column offset and nbins

If a product changes before or during the download (new ETag), `download.sh`
re-discovers it by name. The new header must pass the same regime. The
product is then marked `reprocessed` in `download_plan.tsv` and in the
index. If that happens, the manifest totals must be refreshed after the
build.

## Homogeneity (regime enforced by discover, download, build and verify)

- `TELESCOP=JWST`, `INSTRUME=NIRSPEC`, `DATAMODL=TSOMultiSpecModel`,
  `EXP_TYPE=NRS_BRIGHTOBJ`, `TSOVISIT=T`
- `DETECTOR=NRS1`, `FILTER=F290LP`, `GRATING=G395H`, `FXD_SLIT=S1600A1`,
  `SUBARRAY=SUB2048` (and all products use `READPATT=NRSRAPID`)
- `EXSEGNUM=1`, `INTSTART=1`, and `NAXIS2 = INTEND - INTSTART + 1`
- FLUX is `TFORM nD` with `TUNIT 'Jy'`. WAVELENGTH is `nD` in `um` with the
  same n, and 1000 ≤ n ≤ 2048. Observed n is 1271–1274.

This gives one instrument mode, one detector, one unit, one pipeline step
(`extract_1d`) and one noise process. Target brightness ranges over roughly
1e-4 to 1 Jy. That is a change of scale (exponent) of the same quantity,
not a different tick lattice. Two pipeline versions are present (2.0.1 and
3.0.0). Both are the same TSOMultiSpecModel `extract_1d` output in Jy, and
each sample records its version in the index. Most targets are
transiting-exoplanet host stars. A few are non-transit targets observed in the same BOTS mode, for example
the planetary-mass companion VHS 1256 b and three 2MASS ultracool dwarfs
(program 6474), which were monitored for variability.

## Download (`download.sh`): only the FLUX bytes

For each product, `download.sh`:
1. Fetches header pieces until the `EXTRACT1D` header is complete. A long
   `INT_TIMES` table can require a second piece.
2. Parses the layout with `scripts/x1dints.py`. The FLUX offset inside a row
   is the sum of the TFORM widths of the preceding columns. It is never
   hard-coded (observed: 4 + 8n).
3. Checks the regime with `scripts/check_payload.py header`, against the
   pins in `sources.tsv`.
4. Sends one multi-range request per batch of ≤150 rows. Each range covers
   exactly the 8n FLUX bytes of one row.
5. Checks the response:
   - it must be a 206 with `multipart/byteranges` (boundary taken from
     `Content-Type`), or a single-part 206 when a batch has one range
   - every part must match its planned `Content-Range` exactly
   - ETag and total size must equal those seen during the header walk
   - a missing, extra, truncated or shifted part rejects the batch
6. Retries each request: curl's own retries, plus five outer attempts with
   increasing waits. An ETag change mid-file restarts that file from a
   fresh header walk, up to three times.
7. Uses `--max-filesize` so that a server answering 200 with the whole
   20–270 MB file is aborted. Whole files are never downloaded.
8. Writes the rows, concatenated, to `flux/<stem>.flux.be`, and records
   their SHA-256 in `download_plan.tsv`.
9. Rejects a payload unless every row meets the missing-value policy below.

Expected transfer is about 515 MB: ≈500 MB of FLUX, about 1% multipart
framing and ≈10 MB of header pieces. Batches are resumable: completed
batches are kept until the product is assembled.

## Conversion and missing values

- Each product's whole FLUX matrix is written row-major
  `[integration][wavelength_bin]` as little-endian float64 to
  `samples/<id>/nirspec_g395h_nrs1_x1dints_flux_jy_f64/<stem>.f64`, with
  shape `[NAXIS2, n]`.
- NaN is the pipeline's native fill for bins without valid extraction:
  mostly the first ≈28 and last ≈5 bins of each row, about 2.6% of values.
  It is kept bit-for-bit.
- Every row must be at least 90% finite, have at least 2 distinct finite
  values, and contain no infinities. Otherwise the recipe fails; it does not
  skip the row.
- Every product has exactly one extreme wavelength bin in every row: bin
  230–233, which is column 231 in a 1272-bin grid and moves with n, so it is
  probably a bad detector column. Its values are |flux| > 1000× the median,
  e.g. about −6e3 Jy, and up to ±2.6e6 Jy in a few products where its sign
  alternates. That is 0.08% of all values (49,094 of 62.5 M), measured after
  the build. The values are native pipeline output and are kept unmasked.
  They set the index `finite_min` / `finite_max`, so those fields do not show
  the target's brightness range.
- Index `finite_min` / `finite_max` are computed over finite stored values.

## Verification (`verify.sh`)

`scripts/verify.py` does not import `x1dints.py`. It:
- re-walks the header pieces with its own card parser and re-derives the
  EXTRACT1D offset, the FLUX offset, n and the row count
- checks the primary-header regime
- checks the payload SHA-256
- re-decodes FLUX with `struct` (build uses `array.byteswap`) and
  byte-compares every sample row
- re-applies the NaN policy and rejects constant or duplicate integration
  rows and duplicate samples
- recomputes NaN counts and finite min/max against the index
- checks the manifest `sample_count` / `total_size_bytes`, one product per
  target, at least 40 programs, and the 1 GB cap

`scripts/selftest.py` runs from download.sh and build.sh. On a synthetic
x1dints-like FITS file it tests:
- both header walkers
- range planning
- multipart parsing (CRLF and LF framing, reordered parts)
- the single-range fallback
- every rejection path

## Known caveats

- Consecutive integrations of one star are similar apart from photon noise
  and the transit signal. The material is genuine unrounded float64, from 66
  different stars and visits.
- Segment 1 of an exposure is an archive file boundary, not a physical
  boundary, but it is the natural product record. Later segments and NRS2
  are left out so that targets are spread out rather than visits being
  repeated.
- The products are being reprocessed upstream. If the totals drift, see
  Selection above.
